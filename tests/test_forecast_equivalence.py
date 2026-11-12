"""File/Git guards and read-only comparison tests in isolated temporary projects."""
from pathlib import Path
from importlib.machinery import ModuleSpec
from unittest.mock import Mock
import json
import shutil
import subprocess
from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from homereach.forecasting import equivalence as eq
from homereach.forecasting.core import MODELS, KEY
from homereach.forecasting.evaluation import evaluate_fixed, TABLE_KEYS
from homereach.io.dffh_rent import COLUMN_ORDER, read_panel_csv
from test_forecasting import fake_history

ROOT=Path(__file__).resolve().parents[1]


def write_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


@pytest.mark.parametrize('name',['../a','/a','a/../../x','C:/x','C:\\x','a\\b',''])
def test_unsafe_paths(tmp_path,name):
    with pytest.raises(ValueError):eq.checked_child(tmp_path,name)


def test_safe_child(tmp_path):assert eq.checked_child(tmp_path,'figures/a.html')==tmp_path/'figures/a.html'


def test_resolved_child_escape(tmp_path, monkeypatch):
    # Exercise resolved-path containment without requiring Windows symlink privileges.
    outside=tmp_path/'outside';outside.mkdir();root=tmp_path/'root';root.mkdir()
    child=root/'link/a'; real_resolve=Path.resolve
    def resolved(path, *args, **kwargs):
        return outside/'a' if path == child else real_resolve(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', resolved)
    with pytest.raises(ValueError):eq.checked_child(root,'link/a')


@pytest.mark.parametrize('text',['{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}','[]','not json'])
def test_bad_json(tmp_path,text):
    p=tmp_path/'bad.json';p.write_text(text)
    with pytest.raises(ValueError):eq.load_json(p)


def test_canonical_hash_ignores_layout():assert eq.canonical_hash({'a':1,'b':2})==eq.canonical_hash({'b':2,'a':1})


def test_json_crlf(tmp_path):
    p=tmp_path/'a.json';p.write_bytes(b'\xef\xbb\xbf{\r\n"a": 1\r\n}')
    assert eq.load_json(p)=={'a':1}


def sample_table():return pd.DataFrame({'key':['b','a'],'n':[2,1],'value':[1.23456789,np.nan]})


def test_table_order_invariant():
    f=sample_table();eq.compare_table(f,f.iloc[::-1],['key'],'fixture')


@pytest.mark.parametrize('change',['text','count','float','missing','extra','duplicate','columns','nan'])
def test_mismatched_table_rejected(change):
    a=sample_table();b=a.copy()
    if change=='text':b.loc[0,'key']='wrong'
    elif change=='count':b.loc[0,'n']+=1
    elif change=='float':b.loc[0,'value']+=0.01
    elif change=='missing':b=b.iloc[:1]
    elif change=='extra':b=pd.concat([b,b.iloc[[0]]],ignore_index=True)
    elif change=='duplicate':b.loc[0,'key']='a'
    elif change=='columns':b=b[['n','key','value']]
    else:b.loc[1,'value']=0.
    with pytest.raises(ValueError):eq.compare_table(a,b,['key'],'fixture')


def test_numeric_tolerance_is_unrounded():
    a=sample_table();b=a.copy();b.loc[0,'value']+=1e-10
    eq.compare_table(a,b,['key'],'fixture')
    b.loc[0,'value']+=1e-6
    with pytest.raises(ValueError):eq.compare_table(a,b,['key'],'fixture')


def test_roundtrip_typed_csv(tmp_path):
    f=sample_table();p=tmp_path/'a.csv';f.to_csv(p,index=False)
    eq.compare_table(f,eq.read_saved(p,eq.schema_for(f)),['key'],'fixture')


@pytest.mark.parametrize('schema',[{}, {'a':'object'}, {'a':'pickle'}])
def test_invalid_saved_schema(tmp_path,schema):
    with pytest.raises(ValueError):eq.read_saved(tmp_path/'a.csv',schema)


def test_changed_manifest_payload(tmp_path):
    p=tmp_path/'a';p.write_text('old')
    m={'output_sha256':{'a':eq.fingerprint(p)}};eq.verify_manifest_files(tmp_path,m)
    p.write_text('changed')
    with pytest.raises(ValueError,match='changed'):eq.verify_manifest_files(tmp_path,m)


def test_snapshot_detects_changes_additions_and_ignores_bytecode(tmp_path):
    (tmp_path/'src').mkdir();(tmp_path/'src/a.py').write_text('x=1')
    first=eq.snapshot(tmp_path)
    (tmp_path/'src/__pycache__').mkdir();(tmp_path/'src/__pycache__/a.pyc').write_bytes(b'x')
    assert eq.snapshot(tmp_path)==first
    (tmp_path/'src/b.py').write_text('x=2');assert eq.snapshot(tmp_path)!=first
    (tmp_path/'src/b.py').unlink();(tmp_path/'src/a.py').write_text('x=3');assert eq.snapshot(tmp_path)!=first


@pytest.fixture
def locked_git(tmp_path,monkeypatch):
    if shutil.which('git') is None:pytest.skip('Git is required for this project integration check')
    def git(*args):
        return subprocess.run(['git','-C',str(tmp_path),*args],check=True,capture_output=True).stdout.decode().strip()
    git('init','-b','feat/rental-forecast-baselines')
    git('config','user.name','Test Fixture');git('config','user.email','fixture@example.invalid')
    for relative in [eq.PROTOCOL_FILE,'scripts/verify_rental_final_protocol.py','docs/rental_final_evaluation_protocol.md',
                     'config/rental_forecast_protocol.json','config/rental_ridge_protocol.json',
                     'config/rental_ridge_diagnostic_protocol.json','config/rental_correction_protocol.json']:
        p=tmp_path/relative;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/relative,p)
    git('add','config','scripts','docs');git('commit','-m','fictional protocol lock')
    commit=git('rev-parse','HEAD');monkeypatch.setattr(eq,'LOCK_COMMIT',commit)
    return tmp_path,git


def test_actual_git_lock_gate(locked_git):
    root,git=locked_git;plan,lock=eq.verify_lock(root)
    assert lock['recorded_in_head'] and lock['protocol_commit']==git('rev-parse','HEAD')
    assert eq.canonical_hash(plan)==eq.PROTOCOL_SHA


def test_changed_gate_rejected_before_import(locked_git):
    root,git=locked_git;p=root/'scripts/verify_rental_final_protocol.py';p.write_text('raise RuntimeError("must not execute")')
    with pytest.raises(ValueError,match='verifier changed'):eq.verify_lock(root)


@pytest.mark.parametrize('spec', [None, ModuleSpec('_homereach_frozen_gate', loader=None)],
                         ids=['missing-spec', 'missing-loader'])
def test_unavailable_gate_loader_rejected_before_import(locked_git, monkeypatch, spec):
    root, _ = locked_git
    module_from_spec = Mock(side_effect=AssertionError('Gate import must not be attempted.'))
    monkeypatch.setattr(eq.importlib.util, 'spec_from_file_location', lambda *args: spec)
    monkeypatch.setattr(eq.importlib.util, 'module_from_spec', module_from_spec)
    with pytest.raises(ValueError, match=r'^Cannot import original protocol gate\.$'):
        eq.verify_lock(root)
    module_from_spec.assert_not_called()


def test_wrong_branch_rejected(locked_git):
    root,git=locked_git;git('switch','-c','main')
    with pytest.raises(ValueError,match='Expected branch'):eq.verify_lock(root)


def test_uncommitted_frozen_protocol_rejected(locked_git):
    root,git=locked_git;p=root/eq.PROTOCOL_FILE;o=eq.load_json(p);o['methods'][1]['damping_weight']=0.6;write_json(p,o)
    with pytest.raises(ValueError):eq.verify_lock(root)


def test_changed_prior_protocol_rejected(locked_git):
    root,git=locked_git;p=root/'config/rental_correction_protocol.json';o=eq.load_json(p);o['damping_weight']=0.6;write_json(p,o)
    with pytest.raises(ValueError,match='Earlier protocol changed'):eq.verify_lock(root)


def test_new_research_commit_is_allowed(locked_git):
    root,git=locked_git;(root/'new.txt').write_text('new code');git('add','new.txt');git('commit','-m','fictional subsequent implementation')
    _,lock=eq.verify_lock(root);assert lock['head_commit']!=lock['protocol_commit']


def test_missing_final_evidence_fails_closed(tmp_path):
    with pytest.raises(ValueError,match='Completed notebook 13'):
        eq.load_completed_evidence(tmp_path,{})


@pytest.fixture(scope='module')
def reference_tables():
    # Two FICTIONAL series: exercise all 13 table schemas, not official results.
    f=fake_history(areas=('Fixture A','Fixture B'));return f,*evaluate_fixed(f)


def test_orchestrator_comparison_writes_nothing(tmp_path,monkeypatch,reference_tables):
    f,tables,checks=reference_tables
    plan={'periods':{'final_target_quarters':list(pd.period_range('2023Q4','2025Q3',freq='Q-DEC').astype(str))},
          'rolling_evaluation':{'minimum_training_examples':40}}
    lock={'head_commit':'fixture-head'}
    manifest={'output_schemas':{n:eq.schema_for(df) for n,df in tables.items()},'execution_commit':'original-fixture'}
    path=tmp_path/eq.REFERENCE_DIR/'final_manifest.json';write_json(path,manifest)
    original=path.read_bytes()
    monkeypatch.setattr(eq,'verify_lock',lambda root:(plan,lock))
    monkeypatch.setattr(eq,'load_completed_evidence',lambda root,p:(f,manifest,{n:df.copy(deep=True) for n,df in tables.items()}))
    # Production counts remain strict: the fictional adapter supplies the fixed-scope counters only.
    fixed={'forecasts':992,'trained_fits':496,'lag_checks':97712,'change_checks':73284,
           'baseline_source_checks':496,'source_lineage_rows':992,'coefficient_rows':3224}
    monkeypatch.setattr(eq,'evaluate_fixed',lambda *args,**kwargs:(tables,fixed))
    before=eq.snapshot(tmp_path);result=eq.verify_equivalence(tmp_path,progress=lambda x:None)
    assert result['tables_matched']==13 and result['files_written']==0
    assert eq.snapshot(tmp_path)==before and path.read_bytes()==original


def test_orchestrator_detects_mutation_on_failure(tmp_path,monkeypatch):
    p=tmp_path/'config/a.json';write_json(p,{'a':1})
    monkeypatch.setattr(eq,'verify_lock',lambda root:({},{}))
    def broken(*args):
        p.write_text('changed');raise ValueError('operation failed')
    monkeypatch.setattr(eq,'load_completed_evidence',broken)
    with pytest.raises(ValueError,match='Protected files changed'):
        eq.verify_equivalence(tmp_path,progress=lambda x:None)
