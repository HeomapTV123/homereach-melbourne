"""UI smoke checks. Run with Streamlit installed; do not report skips as passes."""
from pathlib import Path
import pytest
st=pytest.importorskip('streamlit',reason='Streamlit is required for the frozen-release UI tests.')
from streamlit.testing.v1 import AppTest
# Share purely fictional fixtures from the existing UI test module.
from test_explorer_ui import fixture_bundle
from homereach.explorer.release_ui import render_release_method


def test_release_method_renders_licences_and_no_local_paths(fixture_bundle):
    fixture_bundle.manifest['release_id']='a'*64
    at=AppTest.from_string("import streamlit as st\nfrom homereach.explorer.release_ui import render_release_method\nrender_release_method(st.session_state['_fixture'])",default_timeout=30)
    at.session_state['_fixture']=fixture_bundle
    at.run()
    assert not at.exception
    text=' '.join(m.value for m in at.markdown)
    assert 'CC BY 4.0' in text and 'frozen' in text.lower()


def test_release_missing_fails_closed(tmp_path):
    app="from pathlib import Path\nfrom homereach.explorer.release_ui import run_release_app\nrun_release_app(Path("+repr(str(tmp_path/'missing'))+"))"
    at=AppTest.from_string(app,default_timeout=30).run()
    assert not at.exception and any('missing or failed verification' in e.value for e in at.error)
    assert not at.dataframe


def test_release_uses_explicit_folder_not_local_env_override(tmp_path,monkeypatch):
    monkeypatch.setenv('HOMEREACH_PROJECT_ROOT',str(tmp_path/'untrusted'))
    app="from pathlib import Path\nfrom homereach.explorer.release_ui import run_release_app\nrun_release_app(Path("+repr(str(tmp_path/'release'))+"))"
    at=AppTest.from_string(app,default_timeout=30).run()
    assert not at.exception and at.error
