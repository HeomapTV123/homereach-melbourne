"""Fictional forecast regression tests; no official files, internet or existing outputs."""
from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from homereach.forecasting.core import (
    LAST, CANDIDATE, LEVEL, SEASONAL, MODELS, KEY, SERIES, HISTORY_COLUMNS,
    prepare_origin, trained_fit, predict_one, validate_coverage, metrics,
    primary_pairs, summarise_pairs, difference_label,
)
from homereach.forecasting.evaluation import evaluate_fixed, attach_actuals, TABLE_KEYS


def fake_history(n=106, areas=('Fixture A',), constant=False):
    quarters = pd.period_range('1999Q2', periods=n, freq='Q-DEC')
    frames = []
    for j, area in enumerate(areas):
        rents = np.full(n, 500. + 100*j) if constant else 200.+100*j+2*np.arange(n)+5*np.sin(np.arange(n)/3)
        frames.append(pd.DataFrame({'rental_area_name': area, 'property_type': '2 bedroom flats',
                                    'quarter': quarters.astype(str), 'median_weekly_rent': rents,
                                    'source_file': 'fictional.xlsx', 'source_sheet': 'Fixture',
                                    'source_median_cell': [f'D{i+1}' for i in range(n)]}))
    return pd.concat(frames, ignore_index=True)


@pytest.fixture
def history():
    return fake_history()


def forecasts(frame, target='2023Q4'):
    return pd.DataFrame(predict_one(frame, 'Fixture A', '2 bedroom flats', target)[0])


def test_lag_and_change_values(history):
    c = prepare_origin(history, 'Fixture A', '2 bedroom flats', '2023Q4')
    expected = history.iloc[94:98].median_weekly_rent.to_numpy()[::-1]
    np.testing.assert_array_equal(c['predict_level'][:4], expected)
    np.testing.assert_array_equal(c['predict_change'][:3], expected[:-1]-expected[1:])
    assert [r['source_quarter'] for r in c['lineage']] == ['2023Q3','2023Q2','2023Q1','2022Q4']
    assert len(c['y_level']) == 94
    assert c['training_quarters'][0] == pd.Period('2000Q2', freq='Q-DEC')


@pytest.mark.parametrize('target,calendar', [('2023Q4',[0,0,1]), ('2024Q1',[0,0,0]),
                                           ('2024Q2',[1,0,0]), ('2024Q3',[0,1,0])])
def test_calendar_feature_is_known(history, target, calendar):
    c = prepare_origin(history,'Fixture A','2 bedroom flats',target)
    np.testing.assert_array_equal(c['predict_level'][-3:], calendar)
    np.testing.assert_array_equal(c['predict_change'][-3:], calendar)


@pytest.mark.parametrize('model',MODELS)
def test_current_future_mutation_cannot_change_prediction(history, model):
    original = forecasts(history).set_index('model').loc[model,'forecast_weekly_rent_aud']
    changed = history.copy()
    changed.loc[changed.quarter.ge('2023Q4'),'median_weekly_rent'] = 999999
    result = forecasts(changed).set_index('model').loc[model,'forecast_weekly_rent_aud']
    assert original == result


@pytest.mark.parametrize('model',MODELS)
def test_target_and_future_removal(history, model):
    earlier = history.loc[history.quarter.lt('2023Q4')].copy()
    assert forecasts(earlier).set_index('model').loc[model,'forecast_weekly_rent_aud'] == forecasts(history).set_index('model').loc[model,'forecast_weekly_rent_aud']


@pytest.mark.parametrize('model',MODELS)
def test_current_nan_is_not_used_to_predict(history,model):
    changed=history.copy(); changed.loc[changed.quarter.ge('2023Q4'),'median_weekly_rent']=np.nan
    assert forecasts(changed).set_index('model').loc[model,'forecast_weekly_rent_aud'] == forecasts(history).set_index('model').loc[model,'forecast_weekly_rent_aud']


def test_cross_area_and_property_isolation(history):
    extra = history.assign(rental_area_name='Other',median_weekly_rent=9999)
    other_property = history.assign(property_type='other',median_weekly_rent=1)
    assert_frame_equal(forecasts(history),forecasts(pd.concat([history,extra,other_property],ignore_index=True)))


def test_shuffle_invariance(history):
    assert_frame_equal(forecasts(history),forecasts(history.sample(frac=1,random_state=8)))


def test_counts_and_transport_not_predictors(history):
    changed=history.assign(published_count=-100000,transport_indicator=999999)
    assert_frame_equal(forecasts(history),forecasts(changed))


def test_original_frame_unchanged(history):
    before=history.copy(deep=True); forecasts(history); assert_frame_equal(before,history)


@pytest.mark.parametrize('bad', [0,-1,True,1.5])
def test_bad_minimum_rejected(history,bad):
    with pytest.raises(ValueError,match='positive integer'):
        prepare_origin(history,'Fixture A','2 bedroom flats','2023Q4',bad)


@pytest.mark.parametrize('field',HISTORY_COLUMNS)
def test_missing_column_rejected(history,field):
    with pytest.raises(ValueError,match='Missing history'):
        forecasts(history.drop(columns=field))


def test_duplicate_past_rejected(history):
    with pytest.raises(ValueError,match='Duplicate'):
        forecasts(pd.concat([history,history.iloc[[0]]],ignore_index=True))


@pytest.mark.parametrize('index',[0,40,97])
def test_missing_history_rejected(history,index):
    # Removing the first row alone changes the start rather than creating a gap;
    # the production loader pins that boundary. Interior/latest gaps fail here.
    if index == 0:
        assert len(prepare_origin(history.drop(index),'Fixture A','2 bedroom flats','2023Q4')['y_level']) == 93
    else:
        with pytest.raises(ValueError,match='Gap'):
            forecasts(history.drop(index))


def test_insufficient_history():
    with pytest.raises(ValueError,match='Insufficient'):
        forecasts(fake_history(20),'2004Q2')


@pytest.mark.parametrize('bad',[np.nan,np.inf,-np.inf,0,-1])
def test_invalid_past_value(history,bad):
    badframe=history.copy();badframe.loc[20,'median_weekly_rent']=bad
    with pytest.raises(ValueError,match='Invalid past rent'):
        forecasts(badframe)


@pytest.mark.parametrize('field,value',[('source_file','other.xlsx'),('source_sheet','Other'),('source_median_cell','bad')])
def test_bad_source_reference(history,field,value):
    f=history.copy();f.loc[5,field]=value
    with pytest.raises(ValueError,match='source|provenance'):
        forecasts(f)


@pytest.mark.parametrize('field',['source_file','source_sheet','source_median_cell'])
def test_missing_historical_source_reference_rejected(history,field):
    f=history.copy();f.loc[20,field]=None
    with pytest.raises(ValueError,match='source|provenance'):
        forecasts(f)


@pytest.mark.parametrize('field',['source_file','source_sheet'])
@pytest.mark.parametrize('value',['','   '])
def test_blank_historical_source_reference_rejected(history,field,value):
    f=history.copy();f.loc[f.quarter.lt('2023Q4'),field]=value
    with pytest.raises(ValueError,match='source|provenance'):
        forecasts(f)


def test_future_source_metadata_is_not_used_to_predict(history):
    f=history.copy()
    f.loc[f.quarter.ge('2023Q4'),['source_file','source_sheet','source_median_cell']]=None
    assert_frame_equal(forecasts(f),forecasts(history))


@pytest.mark.parametrize('model',MODELS)
def test_constant_series(model):
    assert forecasts(fake_history(constant=True)).set_index('model').loc[model,'forecast_weekly_rent_aud'] == pytest.approx(500,abs=1e-10)


@pytest.mark.parametrize('model',MODELS)
def test_uniform_shift(history,model):
    a=forecasts(history).set_index('model').loc[model,'forecast_weekly_rent_aud']
    b=forecasts(history.assign(median_weekly_rent=history.median_weekly_rent+1000)).set_index('model').loc[model,'forecast_weekly_rent_aud']
    assert b-a == pytest.approx(1000,abs=1e-8)


def test_fixed_half_change_on_linear_series():
    f=fake_history();f.median_weekly_rent=200.+5*np.arange(len(f))
    result=forecasts(f).set_index('model')
    assert result.loc[CANDIDATE,'forecast_weekly_rent_aud']-result.loc[LAST,'forecast_weekly_rent_aud'] == pytest.approx(2.5,abs=1e-9)


def test_negative_finite_prediction_retained():
    f=fake_history(48);f.median_weekly_rent=2.+10*np.arange(47,-1,-1)
    target=str(pd.Period(f.quarter.iloc[-1],freq='Q-DEC')+1)
    r=forecasts(f,target).set_index('model')
    assert r.loc[CANDIDATE,'forecast_weekly_rent_aud'] == pytest.approx(-3,abs=1e-9)
    assert r.loc[CANDIDATE,'prediction_negative'] == 1


@pytest.mark.parametrize('model',[CANDIDATE,LEVEL])
def test_scaler_training_only_and_independent_solution(history,model):
    c=prepare_origin(history,'Fixture A','2 bedroom flats','2023Q4')
    prediction,audit,coefs=trained_fit(c,model)
    assert audit['training_rows']==audit['scaler_training_rows']==94
    assert audit['training_targets_at_or_after_forecast_target']==0
    assert prediction == pytest.approx(audit['independent_forecast_aud_week'],abs=1e-8)
    X=c['X_change' if model==CANDIDATE else 'X_level']
    np.testing.assert_allclose([r['training_mean'] for r in coefs],X.mean(axis=0))
    np.testing.assert_allclose([r['training_variance'] for r in coefs],X.var(axis=0))


def test_earlier_final_observations_enter_later_origins(history):
    a=prepare_origin(history,'Fixture A','2 bedroom flats','2023Q4')
    b=prepare_origin(history,'Fixture A','2 bedroom flats','2024Q1')
    assert len(b['y_level']) == len(a['y_level'])+1
    assert str(b['training_quarters'][-1])=='2023Q4'


def test_unknown_model(history):
    with pytest.raises(ValueError,match='Unknown'):
        trained_fit(prepare_origin(history,'Fixture A','2 bedroom flats','2023Q4'),'new_model')


@pytest.fixture(scope='module')
def evaluated():
    f=fake_history(106,areas=('Fixture A','Fixture B'))
    tables,checks=evaluate_fixed(f)
    return f,tables,checks


def test_all_table_contracts(evaluated):
    f,tables,checks=evaluated
    assert set(tables)==set(TABLE_KEYS)
    assert checks['forecasts']==64 and checks['trained_fits']==32
    assert len(tables['preprocessing_and_coefficients.csv'])==208
    assert len(tables['origin_plan.csv'])==8
    assert tables['origin_plan.csv'].training_rows_per_trained_fit.tolist()==list(range(94,102))


@pytest.mark.parametrize('filename,expected',[('final_metrics_overall.csv',16),('final_metrics_by_lga.csv',8),('final_metrics_by_quarter.csv',2)])
def test_metric_denominators(evaluated,filename,expected):
    assert evaluated[1][filename].n_forecasts.eq(expected).all()


def test_pair_contributions_reconcile(evaluated):
    tables=evaluated[1];overall=tables['primary_comparison_overall.csv'].iloc[0]
    for name in ['primary_comparison_by_lga.csv','primary_comparison_by_quarter.csv']:
        assert tables[name].n_targets.sum()==16
        assert tables[name].contribution_to_pooled_gap_aud_week.sum()==pytest.approx(overall.candidate_minus_last_mae_aud_week)


@pytest.mark.parametrize('change',['remove','duplicate','extra','nan'])
def test_coverage_rejects(evaluated,change):
    f=evaluated[1]['final_predictions.csv'].copy()
    targets=set(map(tuple,f[KEY].to_numpy()))
    if change=='remove': f=f.iloc[1:]
    elif change=='duplicate':f=pd.concat([f,f.iloc[[0]]],ignore_index=True)
    elif change=='extra':f.loc[0,'target_quarter']='2025Q4'
    else:f.loc[0,'forecast_weekly_rent_aud']=np.nan
    with pytest.raises(ValueError):validate_coverage(f,targets,MODELS)


@pytest.mark.parametrize('change',['remove','duplicate','nan'])
def test_actual_join_rejects(evaluated,change):
    f=evaluated[0].copy();p=evaluated[1]['final_predictions.csv']
    p=p.drop(columns=['actual_weekly_rent_aud','target_source_median_cell','source_file','source_sheet',
                      'error_aud_week','absolute_error_aud_week','squared_error'])
    if change=='remove':f=f.loc[~(f.rental_area_name.eq('Fixture A') & f.quarter.eq('2023Q4'))]
    elif change=='duplicate':f=pd.concat([f,f.loc[f.quarter.eq('2023Q4')]],ignore_index=True)
    else:f.loc[f.quarter.eq('2023Q4'),'median_weekly_rent']=np.nan
    with pytest.raises(ValueError):attach_actuals(p,f,['2023Q4','2024Q1','2024Q2','2024Q3','2024Q4','2025Q1','2025Q2','2025Q3'])


@pytest.mark.parametrize('value',[0.,-100.])
def test_nonpositive_final_actual_rejected(history,value):
    f=history.copy();f.loc[f.quarter.eq('2025Q3'),'median_weekly_rent']=value
    with pytest.raises(ValueError,match='actual outcome'):
        evaluate_fixed(f,target_quarters=['2025Q3'])


def test_rmse_is_not_mean_group_rmse():
    f=pd.DataFrame({'model':['a']*2,'forecast_weekly_rent_aud':[0.,10.],'actual_weekly_rent_aud':[0.,0.]})
    row=metrics(f,['model']).iloc[0]
    assert row.mae_aud_week==5 and row.rmse_aud_week==pytest.approx(np.sqrt(50))


@pytest.mark.parametrize('delta,label',[(0,'numerically_tied'),(1e-10,'numerically_tied'),(-1e-10,'numerically_tied'),
                                       (-1,'candidate_lower_mae'),(1,'last_observation_lower_mae')])
def test_numeric_direction(delta,label):assert difference_label(delta)==label


@pytest.mark.parametrize('value',[np.nan,np.inf,-np.inf])
def test_nonfinite_gap(value):
    with pytest.raises(ValueError):difference_label(value)


def test_zero_reference_has_undefined_relative_improvement():
    pairs=pd.DataFrame({'absolute_error_aud_week_last':[0.], 'absolute_error_aud_week_candidate':[0.],
                        'paired_absolute_error_difference_aud_week':[0.]})
    r=summarise_pairs(pairs).iloc[0]
    assert np.isnan(r.relative_mae_improvement_pct)
    assert r.numeric_comparison=='numerically_tied'


@pytest.mark.parametrize('targets',[[],['2024Q1','2023Q4'],['2023Q4','2023Q4'],['2023Q4','2024Q2']])
def test_invalid_target_order(history,targets):
    with pytest.raises(ValueError):evaluate_fixed(history,target_quarters=targets)


def test_primary_actuals_cannot_disagree(evaluated):
    f=evaluated[1]['final_predictions.csv'].copy()
    f.loc[f.model.eq(CANDIDATE),'actual_weekly_rent_aud'] += 1
    with pytest.raises(AssertionError):primary_pairs(f)


def test_empty_metrics():
    with pytest.raises(ValueError):metrics(pd.DataFrame(),['model'])
