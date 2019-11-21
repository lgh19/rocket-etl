import csv, json, requests, sys, traceback
from datetime import date, timedelta
from dateutil import parser
from pprint import pprint

from marshmallow import fields, pre_load, post_load
from engine.wprdc_etl import pipeline as pl
from engine.notify import send_to_slack

try:
    from icecream import ic
except ImportError:  # Graceful fallback if IceCream isn't installed.
    ic = lambda *a: None if not a else (a[0] if len(a) == 1 else a)  # noqa

class JailCensusSchema(pl.BaseSchema):
    date = fields.Date(dump_to='Date')
    gender = fields.String(dump_to='Gender', allow_none=True)
    race = fields.String(dump_to='Race', allow_none=True)
    age_at_booking = fields.String(dump_to='Age at Booking', allow_none=True)
    current_age = fields.String(dump_to='Current Age', allow_none=True)

    class Meta:
        ordered = True

    @pre_load()
    def format_date(self, data):
        data['date'] = date(
            int(data['date'][0:4]),
            int(data['date'][4:6]),
            int(data['date'][6:])).isoformat()


jail_census_package_id = 'd15ca172-66df-4508-8562-5ec54498cfd4' # Production version of Smart Trash Cans package
yesterday = date.today() - timedelta(days=1)

job_dicts = [
    {
        'source_type': 'sftp',
        'source_dir': 'jail_census_data',
        'source_file': 'acj_daily_population_{}.csv'.format(yesterday.strftime('%Y%m%d')),
        'connector_config_string': 'sftp.county_sftp', # This is just used to look up parameters in the settings.json file.
        'upload_method': 'insert', # The deal with the Jail Census ETL job was that there was no good primary key
        # and that the job simply ran daily in insert mode to avoid duplicating entries. We talked about schemes
        # for generating a kind of primary key from the data to avoid this problem, but then the feed stopped
        # providing data, so this entire dataset is on hold for the moment.
        'schema': JailCensusSchema,
        'package': jail_census_package_id,# [ ] Change this field to package_id
        'resource_name': 'ACJ Daily Census Data - {:02d}/{}'.format(yesterday.month, yesterday.year) 
    },
    {
        'source_type': 'sftp',
        'source_dir': 'jail_census_data',
        'source_file': 'acj_daily_population_{}.csv'.format(yesterday.strftime('%Y%m%d')),
        'connector_config_string': 'sftp.county_sftp',
        'upload_method': 'insert',
        'schema': JailCensusSchema,
        'package': jail_census_package_id,# [ ] Change this field to package_id
        'pipeline_name': 'ac_jail_census_cumulative_pipeline', # Not yet used.
        'resource_name': 'ACJ Daily Census Data (Combined)'
    },
]

def process_job(**kwparameters):
    job = kwparameters['job']
    use_local_files = kwparameters['use_local_files']
    clear_first = kwparameters['clear_first']
    test_mode = kwparameters['test_mode']
    job.default_setup(use_local_files)
    locators_by_destination = job.run_pipeline(test_mode, clear_first, file_format='csv')
    # [ ] What is file_format used for? Should it be hard-coded?

    return locators_by_destination # Return a dict allowing look up of final destinations of data (filepaths for local files and resource IDs for data sent to a CKAN instance).
