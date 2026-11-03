# modules/data_loader.py

import pandas as pd

def load_meta_ads_data():
    """
    Stub for Meta Ads Manager API.
    Returns a DataFrame with sample ad performance columns.
    """

    
    sample = {
        'ad_name': ['Ad A', 'Ad B'],
        'impressions': [1000, 1050],
        'clicks': [92, 78],
        'conversions': [12, 9],
        'cost': [1200.0, 1500.0],  # total spend in dollars
        'revenue': [2400.0, 1800.0]   # total revenue in dollars
    }
    return pd.DataFrame(sample)
    

def load_linkedin_campaign_data():
    """
    Stub for LinkedIn Campaign Manager API.
    Returns a DataFrame with sample campaign stats.
    """
    sample = {
        'campaign_name': ['Campaign 1', 'Campaign 2'],
        'impressions': [500, 650],
        'clicks': [40, 55]
    }
    return pd.DataFrame(sample)

def load_ga4_data():
    """
    Stub for Google Analytics 4 API.
    Returns a DataFrame with sample web analytics.
    """
    sample = {
        'page_path': ['/home', '/landing'],
        'users': [200, 180],
        'sessions': [220, 200]
    }
    return pd.DataFrame(sample)
