# modules/cpa_model.py
from scipy.stats import invgamma


def compute_cpa_posterior(alpha_prior, beta_prior, conversions, total_cost):
    """
    Compute posterior parameters for cost-per-acquisition (CPA),
    modeling CPA = cost/conversion via an Inverse-Gamma distribution.

    α_post = α_prior + conversions
    β_post = β_prior + total_cost

    Returns:
      alpha_post (shape),
      beta_post (scale)
    """
    alpha_post = alpha_prior + conversions
    beta_post = beta_prior + total_cost
    return alpha_post, beta_post
