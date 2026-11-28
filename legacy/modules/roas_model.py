# modules/roas_model.py

def compute_roas_posterior(alpha_cpa, beta_cpa, revenue_per_conversion):
    """
    Approximate ROAS posterior as a Gamma distribution:
    - CPA ~ Inv-Gamma(alpha_cpa, beta_cpa)
    - 1/CPA ~ Gamma(alpha_cpa, scale=1/beta_cpa)
    - ROAS = revenue_per_conversion * (1/CPA)
      => Gamma(alpha_cpa, scale=revenue_per_conversion/beta_cpa)
    Returns:
      roas_alpha: shape parameter
      roas_scale: scale parameter
    """
    roas_alpha = alpha_cpa
    roas_scale = revenue_per_conversion / beta_cpa
    return roas_alpha, roas_scale
