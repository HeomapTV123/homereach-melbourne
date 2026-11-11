"""Table-producing fixed evaluation. No reads, exports, tuning, or app changes.

These functions reproduce notebook 13's table contracts. Calling them on the
already-scored final period is an implementation check, not new test evidence.
"""
from __future__ import annotations
from collections.abc import Callable, Sequence
import math
import numpy as np
import pandas as pd
from .core import (
    LAST, CANDIDATE, LEVEL, SEASONAL, MODELS, KEY, SERIES, HISTORY_COLUMNS,
    FINAL_QUARTERS, require, predict_one, validate_coverage, metrics,
    primary_pairs, summarise_pairs,
)

TABLE_KEYS = {
    'final_predictions.csv': ['model', *KEY],
    'final_metrics_overall.csv': ['model'],
    'final_metrics_by_lga.csv': ['model', *SERIES],
    'final_metrics_by_quarter.csv': ['model', 'target_quarter'],
    'primary_paired_errors.csv': KEY,
    'primary_comparison_overall.csv': [],
    'primary_comparison_by_lga.csv': SERIES,
    'primary_comparison_by_quarter.csv': ['target_quarter'],
    'fit_audit.csv': ['model', *KEY],
    'preprocessing_and_coefficients.csv': ['model', *KEY, 'feature'],
    'forecast_feature_lineage.csv': [*KEY, 'lag_quarters'],
    'baseline_source_checks.csv': ['model', *KEY],
    'origin_plan.csv': ['target_quarter'],
}


def attach_actuals(predictions: pd.DataFrame, panel: pd.DataFrame,
                   target_quarters: Sequence[str]) -> pd.DataFrame:
    """Attach outcomes by full key after forecasting, rejecting missing coverage."""
    require('actual_weekly_rent_aud' not in predictions, 'Actuals already attached.')
    actuals = panel.loc[panel.quarter.isin([str(q) for q in target_quarters]),
                       SERIES + ['quarter', 'median_weekly_rent', 'source_file',
                                 'source_sheet', 'source_median_cell']].rename(columns={
        'quarter': 'target_quarter', 'median_weekly_rent': 'actual_weekly_rent_aud',
        'source_median_cell': 'target_source_median_cell'})
    require(not actuals.duplicated(KEY).any(), 'Duplicate actual outcome key.')
    scored = predictions.merge(actuals, on=KEY, how='left', validate='many_to_one', indicator=True)
    require(scored['_merge'].eq('both').all(), 'Missing actual outcome for a forecast.')
    require(np.isfinite(scored.actual_weekly_rent_aud.to_numpy(float)).all(), 'Nonfinite actual outcome.')
    require(scored.actual_weekly_rent_aud.gt(0).all(), 'Nonpositive actual outcome.')
    scored = scored.drop(columns='_merge').sort_values(['model', *KEY]).reset_index(drop=True)
    scored['error_aud_week'] = scored.forecast_weekly_rent_aud - scored.actual_weekly_rent_aud
    scored['absolute_error_aud_week'] = scored.error_aud_week.abs()
    scored['squared_error'] = scored.error_aud_week**2
    return scored


def evaluate_fixed(panel: pd.DataFrame, *,
                   target_quarters: Sequence[str] = tuple(FINAL_QUARTERS.astype(str)),
                   minimum_examples: int = 40,
                   progress: Callable[[str], None] | None = None) -> tuple[dict[str, pd.DataFrame], dict[str, int]]:
    """Recompute fixed methods for explicit origins. Production CLI pins the eight final quarters.

    The optional quarter/minimum arguments support small fictional test fixtures;
    alpha, feature order, damping and estimator remain fixed. No output is written.
    """
    require(set(HISTORY_COLUMNS).issubset(panel), 'Missing rental-history columns.')
    require(len(panel) > 0 and not panel[SERIES + ['quarter']].isna().any().any(), 'Missing/empty series keys.')
    require(not panel.duplicated(SERIES + ['quarter']).any(), 'Duplicate rental key.')
    quarters = pd.PeriodIndex(list(target_quarters), freq='Q-DEC')
    require(len(quarters) > 0 and quarters.equals(pd.period_range(quarters[0], quarters[-1], freq='Q-DEC')),
            'Target quarters must be consecutive, ordered and unique.')
    series = sorted(set(map(tuple, panel[SERIES].to_numpy())))
    expected = {(area, prop, str(q)) for area, prop in series for q in quarters}
    history = panel[HISTORY_COLUMNS].copy()
    lookup = panel.set_index(SERIES + ['quarter'])
    preds, fits, coefs, sources = [], [], [], []
    lag_checks = change_checks = 0
    for index, (area, prop) in enumerate(series, 1):
        for q in quarters:
            pr, fa, cf, ln, nl, nc = predict_one(history, area, prop, q, minimum_examples)
            preds.extend(pr); fits.extend(fa); coefs.extend(cf); sources.extend(ln)
            lag_checks += nl; change_checks += nc
        if progress:
            progress(f'{index:02}/{len(series):02} {area}: fixed forecasts recomputed for comparison.')
    predictions = pd.DataFrame(preds).sort_values(['model', *KEY]).reset_index(drop=True)
    fit_audit = pd.DataFrame(fits).sort_values(['model', *KEY]).reset_index(drop=True)
    coefficients = pd.DataFrame(coefs).sort_values(['model', *KEY, 'feature']).reset_index(drop=True)
    lineage = pd.DataFrame(sources).sort_values([*KEY, 'lag_quarters']).reset_index(drop=True)
    validate_coverage(predictions, expected, MODELS)
    require(len(fit_audit) == 2 * len(expected) and len(lineage) == 4 * len(expected), 'Audit coverage differs.')
    require(fit_audit.training_targets_at_or_after_forecast_target.eq(0).all(), 'Training reached forecast target.')
    require(not fit_audit.duplicated(['model', *KEY]).any(), 'Duplicate fit record.')
    require(not coefficients.duplicated(['model', *KEY, 'feature']).any(), 'Duplicate coefficient record.')
    scored = attach_actuals(predictions, panel, quarters.astype(str).tolist())
    validate_coverage(scored, expected, MODELS)
    for row in lineage.itertuples(index=False):
        src = lookup.loc[(row.rental_area_name, row.property_type, row.source_quarter)]
        require(pd.Period(row.source_quarter, freq='Q-DEC') == pd.Period(row.target_quarter, freq='Q-DEC') - row.lag_quarters,
                'Source quarter differs from forecast lag.')
        require(src.source_median_cell == row.source_median_cell and src.source_file == row.source_file
                and src.source_sheet == row.source_sheet, 'Source provenance differs.')
        np.testing.assert_allclose(float(src.median_weekly_rent), row.rent_aud_week, rtol=0, atol=0)
    baselines = []
    for row in scored.loc[scored.model.isin([LAST, SEASONAL])].itertuples(index=False):
        q = pd.Period(row.target_quarter, freq='Q-DEC') - (1 if row.model == LAST else 4)
        src = lookup.loc[(row.rental_area_name, row.property_type, str(q))]
        np.testing.assert_allclose(row.forecast_weekly_rent_aud, float(src.median_weekly_rent), rtol=0, atol=0)
        baselines.append({'model': row.model, 'rental_area_name': row.rental_area_name,
                          'property_type': row.property_type, 'target_quarter': row.target_quarter,
                          'forecast_origin_quarter': row.forecast_origin_quarter,
                          'forecast_source_quarter': str(q), 'forecast_source_median_cell': src.source_median_cell,
                          'forecast_source_file': src.source_file, 'forecast_source_sheet': src.source_sheet,
                          'forecast_weekly_rent_aud': row.forecast_weekly_rent_aud})
    overall = metrics(scored, ['model'])
    by_lga = metrics(scored, ['model', *SERIES])
    by_quarter = metrics(scored, ['model', 'target_quarter'])
    for model in MODELS:
        g = scored.loc[scored.model.eq(model)]
        m = overall.set_index('model').loc[model]
        n = len(expected)
        np.testing.assert_allclose([m.mae_aud_week, m.rmse_aud_week, m.mean_signed_error_aud_week],
                                  [math.fsum(g.absolute_error_aud_week)/n,
                                   math.sqrt(math.fsum(g.squared_error)/n), math.fsum(g.error_aud_week)/n],
                                  rtol=1e-12, atol=1e-12)
        require(int(m.n_forecasts) == n, 'Wrong pooled metric denominator.')
        for grouped in (by_lga, by_quarter):
            x = grouped.loc[grouped.model.eq(model)]
            require(int(x.n_forecasts.sum()) == n, 'Wrong grouped denominator.')
            np.testing.assert_allclose(np.average(x.mae_aud_week, weights=x.n_forecasts), m.mae_aud_week, atol=1e-12)
            np.testing.assert_allclose(np.sqrt(np.average(x.rmse_aud_week**2, weights=x.n_forecasts)), m.rmse_aud_week, atol=1e-12)
    pairs = primary_pairs(scored)
    primary = summarise_pairs(pairs)
    primary_lga = summarise_pairs(pairs, SERIES)
    primary_quarter = summarise_pairs(pairs, ['target_quarter'])
    for grouped in (primary_lga, primary_quarter):
        require(int(grouped.n_targets.sum()) == len(expected), 'Paired groups omit a target.')
        np.testing.assert_allclose(grouped.contribution_to_pooled_gap_aud_week.sum(),
                                   primary.iloc[0].candidate_minus_last_mae_aud_week, atol=1e-10)
    # Derive the origin table from actual fit ranges; identical to notebook 13 on its fixed scope.
    origin_records = []
    for i, q in enumerate(quarters):
        f = fit_audit.loc[fit_audit.target_quarter.eq(str(q))]
        require(f.training_first_target.nunique() == 1 and f.training_rows.nunique() == 1,
                'Origin table requires identical history coverage across series.')
        origin_records.append({'target_quarter': str(q), 'forecast_origin_quarter': str(q-1),
                               'training_first_target': str(f.iloc[0].training_first_target),
                               'training_last_target': str(q-1),
                               'training_rows_per_trained_fit': int(f.iloc[0].training_rows),
                               'earlier_final_outcomes_available': i, 'targets_per_method': len(series)})
    tables = {
        'final_predictions.csv': scored,
        'final_metrics_overall.csv': overall,
        'final_metrics_by_lga.csv': by_lga,
        'final_metrics_by_quarter.csv': by_quarter,
        'primary_paired_errors.csv': pairs,
        'primary_comparison_overall.csv': primary,
        'primary_comparison_by_lga.csv': primary_lga,
        'primary_comparison_by_quarter.csv': primary_quarter,
        'fit_audit.csv': fit_audit,
        'preprocessing_and_coefficients.csv': coefficients,
        'forecast_feature_lineage.csv': lineage,
        'baseline_source_checks.csv': pd.DataFrame(baselines),
        'origin_plan.csv': pd.DataFrame(origin_records),
    }
    checks = {'forecasts': len(scored), 'trained_fits': len(fit_audit), 'lag_checks': lag_checks,
              'change_checks': change_checks, 'baseline_source_checks': len(baselines),
              'source_lineage_rows': len(lineage), 'coefficient_rows': len(coefficients)}
    return tables, checks
