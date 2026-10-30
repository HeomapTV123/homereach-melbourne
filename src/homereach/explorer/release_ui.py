"""Hosting entry point: reuse the tested explorer pages, read only frozen release data."""
from pathlib import Path
import streamlit as st
from packaging.version import Version
from .bundle import ExplorerBundle
from .release import ATTRIBUTIONS, load_release, release_signature
from .ui import render_compare, render_area, render_map, period_banner
from .analysis import AM_WINDOW
import json

@st.cache_data(show_spinner=False, max_entries=2)
def cached_release(folder: str, signature: str) -> ExplorerBundle:
    return load_release(Path(folder), expected_signature=signature)


def render_release_method(bundle: ExplorerBundle) -> None:
    st.title('Data and methodology')
    period_banner()
    st.dataframe(bundle.tables['source_periods.csv'][['component', 'period', 'scope']], hide_index=True, width='stretch')
    st.subheader('What this release verifies')
    st.write('This is a frozen, self-contained release of previously validated local pipeline outputs. '
             'The app checks the packaged file fingerprints, schemas and cross-table relationships. '
             'It does not re-run the raw-data audits on the hosting server or fetch current rents and timetables.')
    st.caption('Fingerprints detect changes relative to the release manifest, not publisher signatures or independent certification.')
    st.subheader('Counting rule and interpretation')
    st.write('One scheduled event is an active feed/trip/stop-sequence record with regular pickup, '
             'a later stop in the complete trip and a stop assigned to one selected LGA. '
             'Calendar exceptions apply; labelled replacement buses stay separate. '
             'The morning window is 07:00 inclusive to 09:00 exclusive. Complete service days retain times after 24:00.')
    totals = bundle.tables['study_area_reconciliation.csv']
    am = totals.loc[totals.window.eq(AM_WINDOW)].iloc[0]
    st.write(f'Distinct study-area morning trips: **{int(am.distinct_study_area_trips):,}**. '
             f'Adding LGA trip counts instead gives **{int(am.sum_of_lga_trip_counts_not_a_study_area_total):,}**, '
             'which counts trips visiting multiple LGAs more than once.')
    st.warning('Area medians are not live listings or household affordability measures. Scheduled counts are not '
               'vehicles, riders, actual performance, waiting times or commute times. LGA size and stop placement '
               'affect raw counts. No scores, forecasts or area recommendations are produced.')
    st.write('The newer transport snapshot is not inserted into historical rental-model validation. '
             'Unknown accessibility information is not interpreted as inaccessible. '
             'Point-in-polygon membership is not a walking-catchment or destination-access analysis.')
    st.subheader('Sources, licence and changes')
    st.caption(ATTRIBUTIONS['endorsement'])
    for source in ATTRIBUTIONS['sources']:
        st.markdown(f"**{source['publisher']}**")
        st.write(source['dataset'])
        st.markdown(f"[Source dataset]({source['source_url']}) · [Licence evidence]({source['licence_evidence']}) · "
                    f"[{source['licence']}]({source['licence_url']})")
        st.caption('HomeReach processing: ' + source['changes'])
    st.caption(ATTRIBUTIONS['licence_scope'])
    st.subheader('Frozen release record')
    st.write('Created (UTC):', bundle.manifest['created_at_utc'])
    st.code(bundle.manifest['release_id'], language=None)
    st.json(bundle.manifest['quality'], expanded=False)
    st.download_button('Download the public release manifest', json.dumps(bundle.manifest, indent=2),
                       file_name='homereach_release_manifest.json', mime='application/json', key='release_manifest_download')
    st.caption('This release changes only through a reviewed rebuild and deployment, not automatically when the publishers update their feeds.')


def run_release_app(folder: Path) -> None:
    st.set_page_config(page_title='HomeReach Melbourne | Published-data explorer', page_icon='🏠', layout='wide')
    if Version(st.__version__) < Version('1.50.0'):
        st.error('This app needs Streamlit 1.50 or later. Use deploy/requirements.txt for the hosted environment.')
        st.stop()
    try:
        signature = release_signature(folder)
        bundle = cached_release(str(folder.resolve()), signature)
    except (OSError, ValueError, KeyError, TypeError) as error:
        st.title('HomeReach Melbourne')
        st.error('The packaged release is missing or failed verification.')
        st.caption('Maintainer: run scripts/package_explorer.py locally and review the release. No synthetic fallback was loaded.')
        with st.expander('Release verification details'):
            st.code(str(error), language=None)
        st.stop()
    with st.sidebar:
        st.header('HomeReach Melbourne')
        st.caption('REAL-DATA EXPLORER · FROZEN RELEASE')
        st.caption('31 source-group LGAs\n\nTwo-bedroom flats\n\nNo scores or predictions')
        st.caption('Release: ' + bundle.manifest['release_id'][:12])
    def compare(): render_compare(bundle)
    def area(): render_area(bundle)
    def map_page(): render_map(bundle)
    def methodology(): render_release_method(bundle)
    page = st.navigation([
        st.Page(compare, title='Compare LGAs', icon=':material/compare_arrows:', default=True),
        st.Page(area, title='Area details', icon=':material/location_city:', url_path='area'),
        st.Page(map_page, title='Rental map', icon=':material/map:', url_path='map'),
        st.Page(methodology, title='Data and methodology', icon=':material/info:', url_path='methodology'),
    ])
    page.run()
