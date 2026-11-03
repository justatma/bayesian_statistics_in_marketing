# modules/cvr_model.py
from scipy.stats import beta


def compute_cvr_posterior(alpha_prior, beta_prior, conversions, clicks):
    """
    Compute alpha and beta for posterior Beta distribution of CVR.
    """
    alpha_post = alpha_prior + conversions
    beta_post = beta_prior + clicks - conversions
    return alpha_post, beta_post
