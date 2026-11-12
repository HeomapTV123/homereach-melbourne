"""Fixed rental forecasts extracted from notebook 13; no I/O or model selection.

Only historical observations are passed to prediction functions. Actual outcomes
are attached after every prediction exists. This implements the recorded method;
recomputing it is not another independent final test.
"""
from __future__ import annotations
from collections.abc import Callable, Sequence
from typing import Any
from types import MappingProxyType
import math

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

LAST = "last_observation"
CANDIDATE = "damped_change_ridge_alpha1_weight05"
LEVEL = "ridge_lags_seasonal_alpha1"
SEASONAL = "seasonal_naive"
MODELS = (LAST, CANDIDATE, LEVEL, SEASONAL)
KEY = ["rental_area_name", "property_type", "target_quarter"]
SERIES = KEY[:2]
HISTORY_COLUMNS = SERIES + ["quarter", "median_weekly_rent", "source_file", "source_sheet", "source_median_cell"]
FINAL_QUARTERS = pd.period_range("2023Q4", "2025Q3", freq="Q-DEC")
TOLERANCE = 1e-9
LEVEL_FEATURES = [f"rent_lag_{k}" for k in range(1, 5)] + [f"target_is_q{k}" for k in (2, 3, 4)]
CHANGE_FEATURES = [f"change_lag_{k}" for k in range(1, 4)] + [f"target_is_q{k}" for k in (2, 3, 4)]
# These are the committed specifications, not configurable tuning arguments.
METHOD = {
    LAST: {"role": "primary_reference"},
    CANDIDATE: {"role": "primary_candidate", "alpha": 1.0, "damping_weight": 0.5,
                "fit_intercept": True, "solver": "svd", "with_mean": True, "with_std": True},
    LEVEL: {"role": "secondary_reference_only", "alpha": 1.0,
            "fit_intercept": True, "solver": "svd", "with_mean": True, "with_std": True},
    SEASONAL: {"role": "secondary_reference_only"},
}


def require(condition: Any, message: str) -> None:
    if not bool(condition):
        raise ValueError(message)


METHOD = MappingProxyType({name: MappingProxyType(value) for name, value in METHOD.items()})

def prepare_origin(frame: pd.DataFrame, area: str, property_type: str,
                   target: str | pd.Period, minimum_examples: int = 40) -> dict[str, Any]:
    """Read this series only through t-1. Target/future rent values are never required."""
    require(isinstance(minimum_examples, int) and not isinstance(minimum_examples, bool)
            and minimum_examples >= 1, 'minimum_examples must be a positive integer.')
    q = pd.Period(target, freq='Q-DEC')
    require(set(HISTORY_COLUMNS).issubset(frame.columns), 'Missing history columns.')
    own = frame.loc[frame.rental_area_name.eq(area) & frame.property_type.eq(property_type), HISTORY_COLUMNS].copy()
    own['_q'] = pd.PeriodIndex(own.quarter, freq='Q-DEC')
    past = own.loc[own['_q'].lt(q)].sort_values('_q', kind='stable').reset_index(drop=True)
    require(not past.duplicated(SERIES+['quarter']).any(), 'Duplicate past history key.')
    require(len(past) >= 4+minimum_examples, 'Insufficient earlier supervised history.')
    periods = pd.PeriodIndex(past['_q'], freq='Q-DEC')
    require(periods.equals(pd.period_range(periods[0], q-1, freq='Q-DEC')), 'Gap in past history or missing latest quarter.')
    values = past.median_weekly_rent.to_numpy(dtype=float)
    require(np.isfinite(values).all() and (values > 0).all(), 'Invalid past rent.')
    # Pandas reductions skip missing values by default. Validate provenance
    # explicitly, and only for the selected history so future data stays unused.
    for field in ('source_file', 'source_sheet', 'source_median_cell'):
        labels = past[field].astype('string')
        require(labels.notna().all() and labels.str.strip().ne('').all(), 'Missing or blank past source provenance.')
    require(past.source_median_cell.astype('string').str.fullmatch(r'[A-Z]+[1-9][0-9]*', na=False).all(), 'Invalid past source cells.')
    require(past.source_file.nunique() == past.source_sheet.nunique() == 1, 'Mixed source provenance within history.')
    train_q = periods[4:]
    lags = np.column_stack([values[4-k:len(values)-k] for k in range(1,5)])
    calendar = np.column_stack([(train_q.quarter==k).astype(float) for k in [2,3,4]])
    final_lags = values[-4:][::-1].copy()
    final_calendar = np.array([float(q.quarter==k) for k in [2,3,4]])
    X_level = np.column_stack([lags,calendar])
    X_change = np.column_stack([lags[:,:3]-lags[:,1:4],calendar])
    predict_level = np.r_[final_lags,final_calendar]
    predict_change = np.r_[final_lags[:3]-final_lags[1:],final_calendar]
    y_level = values[4:].copy()
    y_change = y_level-lags[:,0]
    # Independent dictionary lookups check every historical lag and quarterly change.
    lookup = {str(r.quarter):r for r in past.itertuples(index=False)}
    lag_checks = change_checks = 0
    for i,t in enumerate(train_q):
        expected = np.array([float(lookup[str(t-k)].median_weekly_rent) for k in range(1,5)])
        np.testing.assert_array_equal(lags[i],expected)
        require(t < q, 'A training target reached the forecast target.')
        np.testing.assert_array_equal(X_change[i,:3],expected[:3]-expected[1:])
        lag_checks += 4; change_checks += 3
    expected = np.array([float(lookup[str(q-k)].median_weekly_rent) for k in range(1,5)])
    np.testing.assert_array_equal(final_lags,expected)
    lag_checks += 4; change_checks += 3
    lineage = []
    for k in range(1,5):
        src = lookup[str(q-k)]
        lineage.append({'lag_quarters':k, 'source_quarter':str(q-k), 'rent_aud_week':float(src.median_weekly_rent),
                        'source_file':str(src.source_file),'source_sheet':str(src.source_sheet),
                        'source_median_cell':str(src.source_median_cell)})
    return {'target':q,'periods':periods,'training_quarters':train_q,'last':float(values[-1]),
            'seasonal':float(values[-4]),'X_level':X_level,'X_change':X_change,
            'predict_level':predict_level,'predict_change':predict_change,
            'y_level':y_level,'y_change':y_change,'lineage':lineage,
            'lag_checks':lag_checks,'change_checks':change_checks}


def trained_fit(context: dict[str, Any], model: str) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    """Fresh training-only scaling and Ridge fit; independent normal-equation check."""
    require(model in [CANDIDATE,LEVEL], 'Unknown trained method.')
    setting = METHOD[model]
    change_model = model==CANDIDATE
    X = context['X_change' if change_model else 'X_level']
    y = context['y_change' if change_model else 'y_level']
    xp = context['predict_change' if change_model else 'predict_level']
    names = CHANGE_FEATURES if change_model else LEVEL_FEATURES
    require(np.isfinite(X).all() and np.isfinite(y).all() and np.isfinite(xp).all(), 'Nonfinite training value.')
    pipeline = Pipeline([('scale',StandardScaler(with_mean=setting['with_mean'],with_std=setting['with_std'])),
                         ('ridge',Ridge(alpha=setting['alpha'],fit_intercept=setting['fit_intercept'],solver=setting['solver']))])
    pipeline.fit(pd.DataFrame(X,columns=names), y)
    raw_prediction = float(pipeline.predict(pd.DataFrame([xp],columns=names))[0])
    scaler = pipeline.named_steps['scale']; ridge = pipeline.named_steps['ridge']
    n = len(y)
    require(int(scaler.n_samples_seen_)==n, 'Scaler fitted on the wrong number of rows.')
    np.testing.assert_allclose(scaler.mean_,X.mean(axis=0),rtol=1e-12,atol=1e-12)
    np.testing.assert_allclose(scaler.var_,X.var(axis=0),rtol=1e-12,atol=1e-12)
    # Independent scaling is computed directly; constant columns keep scale 1.
    independent_scale = np.sqrt(X.var(axis=0)); independent_scale[independent_scale==0] = 1.0
    np.testing.assert_allclose(scaler.scale_,independent_scale,rtol=1e-12,atol=1e-12)
    z = (X-X.mean(axis=0))/independent_scale
    zbar = z.mean(axis=0); ybar = float(y.mean())
    centered = z-zbar
    coefficients_check = np.linalg.solve(centered.T@centered+setting['alpha']*np.eye(len(names)), centered.T@(y-ybar))
    independent_raw = float(((xp-X.mean(axis=0))/independent_scale-zbar)@coefficients_check+ybar)
    np.testing.assert_allclose(raw_prediction,independent_raw,rtol=1e-9,atol=1e-8)
    forecast = context['last']+setting['damping_weight']*raw_prediction if change_model else raw_prediction
    independent_forecast = context['last']+setting['damping_weight']*independent_raw if change_model else independent_raw
    np.testing.assert_allclose(forecast,independent_forecast,rtol=1e-9,atol=1e-8)
    require(np.isfinite(forecast), 'Nonfinite forecast; stop rather than omit this target.')
    raw_coefficients = ridge.coef_/scaler.scale_
    raw_intercept = float(ridge.intercept_-raw_coefficients@scaler.mean_)
    np.testing.assert_allclose(raw_prediction,raw_intercept+xp@raw_coefficients,rtol=1e-9,atol=1e-8)
    training_q = context['training_quarters']
    audit = {'training_first_target':str(training_q[0]),'training_last_target':str(training_q[-1]),
             'training_rows':n,'scaler_training_rows':int(scaler.n_samples_seen_),
             'earlier_final_targets_in_training':int((training_q>=FINAL_QUARTERS[0]).sum()),
             'training_targets_at_or_after_forecast_target':int((training_q>=context['target']).sum()),
             'alpha':float(setting['alpha']),'raw_model_prediction_aud_week':raw_prediction,
             'independent_raw_prediction_aud_week':independent_raw,'independent_forecast_aud_week':independent_forecast,
             'training_target_mean':ybar,'raw_intercept':raw_intercept,
             'prediction_negative':int(forecast<0)}
    evidence = [{'feature':name,'training_mean':float(scaler.mean_[j]),'training_variance':float(scaler.var_[j]),
                 'training_scale':float(scaler.scale_[j]),'coefficient_standardized':float(ridge.coef_[j]),
                 'coefficient_raw_units':float(raw_coefficients[j]),'forecast_feature_value':float(xp[j])}
                for j,name in enumerate(names)]
    return float(forecast), audit, evidence


def predict_one(frame: pd.DataFrame, area: str, property_type: str,
                target: str | pd.Period, minimum_examples: int = 40) -> tuple:
    c = prepare_origin(frame,area,property_type,target,minimum_examples)
    key = {'rental_area_name':area,'property_type':property_type,'target_quarter':str(c['target']),
           'forecast_origin_quarter':str(c['target']-1)}
    predictions=[]; fits=[]; coefs=[]
    for model in MODELS:
        if model==LAST: prediction=c['last']
        elif model==SEASONAL: prediction=c['seasonal']
        else:
            prediction,audit,coefficients=trained_fit(c,model)
            fits.append({**key,'model':model,**audit})
            coefs.extend({**key,'model':model,**record} for record in coefficients)
        predictions.append({**key,'model':model,'model_role':METHOD[model]['role'],
                            'last_observed_rent_aud_week':c['last'],
                            'forecast_weekly_rent_aud':float(prediction),'prediction_negative':int(prediction<0)})
    lineage=[{**key,**record} for record in c['lineage']]
    return predictions,fits,coefs,lineage,c['lag_checks'],c['change_checks']


def validate_coverage(frame: pd.DataFrame, target_keys: set[tuple], models: Sequence[str]) -> None:
    require(not frame.duplicated(['model',*KEY]).any(),'Duplicate model/target key.')
    require(set(frame.model)==set(models),'Method coverage differs.')
    for model,group in frame.groupby('model'):
        require(set(map(tuple,group[KEY].to_numpy()))==set(target_keys),'Missing or extra forecast target.')
    require(np.isfinite(frame.forecast_weekly_rent_aud.to_numpy(float)).all(),'Nonfinite prediction.')


def difference_label(delta: float) -> str:
    require(np.isfinite(delta), "Nonfinite paired difference.")
    if delta < -TOLERANCE: return 'candidate_lower_mae'
    if delta > TOLERANCE: return 'last_observation_lower_mae'
    return 'numerically_tied'


def primary_pairs(scored: pd.DataFrame) -> pd.DataFrame:
    ref=scored.loc[scored.model.eq(LAST),KEY+['actual_weekly_rent_aud','forecast_weekly_rent_aud','absolute_error_aud_week']].copy()
    cand=scored.loc[scored.model.eq(CANDIDATE),KEY+['actual_weekly_rent_aud','forecast_weekly_rent_aud','absolute_error_aud_week']].copy()
    result=ref.merge(cand,on=KEY,how='outer',validate='one_to_one',indicator=True,suffixes=('_last','_candidate'))
    require(result['_merge'].eq('both').all(),'Primary comparison targets differ.')
    np.testing.assert_array_equal(result.actual_weekly_rent_aud_last,result.actual_weekly_rent_aud_candidate)
    result=result.drop(columns=['_merge','actual_weekly_rent_aud_candidate']).rename(columns={'actual_weekly_rent_aud_last':'actual_weekly_rent_aud'})
    result['paired_absolute_error_difference_aud_week']=result.absolute_error_aud_week_candidate-result.absolute_error_aud_week_last
    return result.sort_values(KEY).reset_index(drop=True)


def summarise_pairs(pairs: pd.DataFrame, groups: Sequence[str] = ()) -> pd.DataFrame:
    require(len(pairs) > 0, "Empty paired comparison.")
    rows=[]
    group_iterator=pairs.groupby(list(groups),sort=True,dropna=False,observed=True) if groups else [((),pairs)]
    for values,g in group_iterator:
        values=(values,) if not isinstance(values,tuple) else values
        last=float(g.absolute_error_aud_week_last.mean());candidate=float(g.absolute_error_aud_week_candidate.mean())
        delta=float(g.paired_absolute_error_difference_aud_week.mean())
        np.testing.assert_allclose(delta,candidate-last,rtol=1e-10,atol=1e-10)
        rows.append({**dict(zip(groups,values)),'n_targets':len(g),'last_mae_aud_week':last,
                     'candidate_mae_aud_week':candidate,'candidate_minus_last_mae_aud_week':delta,
                     'relative_mae_improvement_pct':100*(last-candidate)/last if last else np.nan,
                     'sum_paired_loss_difference':float(g.paired_absolute_error_difference_aud_week.sum()),
                     'contribution_to_pooled_gap_aud_week':float(g.paired_absolute_error_difference_aud_week.sum()/len(pairs)),
                     'numeric_comparison':difference_label(delta)})
    return pd.DataFrame(rows)


def metrics(frame: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    require(len(frame) > 0 and len(groups) > 0, "Empty metric input or grouping.")
    rows=[]
    for values,g in frame.groupby(groups,sort=True,dropna=False,observed=True):
        values=(values,) if not isinstance(values,tuple) else values
        errors=g.forecast_weekly_rent_aud.to_numpy(float)-g.actual_weekly_rent_aud.to_numpy(float)
        require(len(errors)>0 and np.isfinite(errors).all(),'Nonfinite or empty forecast errors.')
        rows.append({**dict(zip(groups,values)), 'n_forecasts':len(errors),
                     'mae_aud_week':float(np.abs(errors).mean()),
                     'rmse_aud_week':float(np.sqrt(np.mean(errors**2))),
                     'mean_signed_error_aud_week':float(errors.mean())})
    return pd.DataFrame(rows)


