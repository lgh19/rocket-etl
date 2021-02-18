import csv, json, requests, sys, traceback, re, time
from datetime import datetime
from dateutil import parser
from pprint import pprint
from collections import OrderedDict, defaultdict

from marshmallow import fields, pre_load, post_load
from engine.wprdc_etl import pipeline as pl
from engine.etl_util import fetch_city_file
from engine.notify import send_to_slack

try:
    from icecream import ic
except ImportError:  # Graceful fallback if IceCream isn't installed.
    ic = lambda *a: None if not a else (a[0] if len(a) == 1 else a)  # noqa


# Network functions #
import socket

def get_an_ip_for_host(host):
    try:
        ips = socket.gethostbyname_ex(host)
    except socket.gaierror:
        return None
    return ips[0]

def site_is_up(site):
    """At present, geo.wprdc.org is only accessible from inside the Pitt network.
    Therefore, it's helpful to run this function to check whether this script
    should even try to do any geocoding."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2) # Add a two-second timeout to avoid interminable waiting.
    ip = get_an_ip_for_host(site)
    if ip is None:
        print("Unable to get an IP address for that host.")
        return False
    result = sock.connect_ex((ip,80))
    if result == 0:
        print('port OPEN')
        return True
    else:
        print('port CLOSED, connect_ex returned: '+str(result))
        return False

# End network functions #

class MultifamilyInsuredMortgagesSchema(pl.BaseSchema):
    job_code = 'mimortgages'
    hud_property_name = fields.String(load_from='property_name', dump_to='hud_property_name')
    property_street_address = fields.String(load_from='property_street', dump_to='property_street_address', allow_none=True)
    fha_loan_id = fields.String(load_from='hud_project_number', dump_to='fha_loan_id')
    city = fields.String(load_from='PROPERTY_CITY'.lower(), dump_to='city')
    state = fields.String(load_from='PROPERTY_STATE'.lower(), dump_to='state')
    zip_code = fields.String(load_from='PROPERTY_ZIP'.lower(), dump_to='zip_code')
    units = fields.Integer(load_from='UNITS'.lower(), dump_to='units')
    initial_endorsement_date = fields.Date(load_from='INITIAL ENDORSEMENT DATE'.lower(), dump_to='initial_endorsement_date')
    #final_endorsement_date = fields.String(load_from='FINAL ENDORSEMENT DATE'.lower(), allow_none=True)
    original_mortgage_amount = fields.Integer(load_from='ORIGINAL MORTGAGE AMOUNT'.lower(), dump_to='original_mortgage_amount')
    #first_payment_date = fields.String(load_from='FIRST PAYMENT DATE'.lower())
    maturity_date = fields.Date(load_from='MATURITY DATE'.lower(), dump_to='maturity_date')
    term_in_months = fields.Integer(load_from='TERM IN MONTHS'.lower(), dump_to='term_in_months')
    interest_rate = fields.Float(load_from='INTEREST RATE'.lower(), dump_to='interest_rate')
    current_principal_and_interest = fields.Float(load_from='CURRENT PRINCIPAL AND INTEREST'.lower(), dump_to='current_principal_and_interest')
    amoritized_principal_balance = fields.Float(load_from='AMORITIZED PRINCIPAL BALANCE'.lower(), dump_to='amoritized_principal_balance')
    holder_name = fields.String(load_from='HOLDER NAME'.lower(), dump_to='holder_name')
    holder_city = fields.String(load_from='HOLDER CITY'.lower(), dump_to='holder_city')
    holder_state = fields.String(load_from='HOLDER STATE'.lower(), dump_to='holder_state')
    servicer_name = fields.String(load_from='SERVICER NAME'.lower(), dump_to='servicer_name')
    servicer_city = fields.String(load_from='SERVICER CITY'.lower(), dump_to='servicer_city')
    servicer_state = fields.String(load_from='SERVICER STATE'.lower(), dump_to='servicer_state')
    section_of_act_code = fields.String(load_from='SECTION OF ACT CODE'.lower(), dump_to='section_of_act_code')
    soa_category_sub_category = fields.String(load_from='SOA_CATEGORY/SUB_CATEGORY'.lower(), dump_to='program_category')
    #te = fields.String(load_from='TE'.lower(), allow_none=True)
    #tc = fields.String(load_from='TC'.lower(), allow_none=True)

    class Meta:
        ordered = True

    @pre_load
    def fix_dates(self, data):
        """Marshmallow doesn't know how to handle a datetime as input. It can only
        take strings that represent datetimes and convert them to datetimes.:
        https://github.com/marshmallow-code/marshmallow/issues/656
        So this is a workaround.
        """
        date_fields = ['maturity_date', 'initial_endorsement_date']
        for f in date_fields:
            data[f] = data[f].date().isoformat()

    @post_load
    def handle_weird_field_name(self, data):
        data['program_category'] = data['soa_category_sub_category']
# dfg

job_dicts = [
    {
        'update': 0,
        'job_code': MultifamilyInsuredMortgagesSchema().job_code, #'mimortgages'
        #This Excel 2018 file includes all active HUD Multifamily insured mortgages. The data is as of  January 4, 2021 and is updated monthly. It is extracted from MFIS and includes the following data elements:
        #   FHA Project Number
        #   Project Name
        #   Project Street
        #   Project City
        #   Project State
        #   Project Zip Code
        #   Number of total Units (or total beds for health and hospital care)
        #   Initial Endorsement Date
        #   Final Endorsement Date
        #   Original Mortgage Amount
        #   First Payment Date
        #   Maturity Date
        #   Term of loan in months
        #   Interest Rate
        #   Monthly Principal and Interest Payment
        #   Amortized Unpaid Principal Balance
        #   Holder Name
        #   Holder City
        #   Holder State
        #   Servicer Name
        #   Servicer City
        #   Servicer State
        #   Section of the Act Code (SoA)
        #   Section of the Act Category/Sub Category (Note: SOA codes are available on this list: SoA_list.xlsx.)
        #    
        #   Tax Exempt Bond Financing Code (Mortgages financed by tax exempt bonds are indicated by "TE" code. This field was updated on new endorsements beginning in CY 2000).
        #    
        #   Tax Credit Code (Mortgages that include Low Income Housing Tax Credits (LIHTC) are indicated by the "TC" code. This field was updated on endorsements beginning in the middle of 1998.)
        'source_type': 'http',
        #'source_type': 'local',
        'source_url_path': 'https://www.hud.gov/sites/dfiles/Housing/images',
        'source_file': 'FHA_BF90_RM_A_01042021.xlsx',
        'encoding': 'binary',
        'schema': MultifamilyInsuredMortgagesSchema,
        'filters': [['property_state', '==', 'PA']],
        'always_wipe_data': True,
        'primary_key_fields': ['hud_project_number'], # "HUD PROJECT NUMBER" seems pretty unique.
        'destinations': ['file'],
        'destination_file': 'multifamily_insured_mortgages.csv',
    },
]

assert len(job_dicts) == len({d['job_code'] for d in job_dicts}) # Verify that all job codes are unique.
