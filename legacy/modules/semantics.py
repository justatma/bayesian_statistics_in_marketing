# modules/semantics.py

def explain_prior_impact(alpha_prior, beta_prior):
    """
    Returns a textual explanation of how a Beta(alpha, beta) prior shapes
    initial beliefs before seeing data.
    """
    total = alpha_prior + beta_prior
    mean = alpha_prior / total
    return (
        f"A Beta prior with α={alpha_prior} and β={beta_prior} "
        f"implies an initial mean estimate of {mean:.2%} for the CTR. "
        "Stronger priors (larger α+β) indicate more confidence before seeing new data."
    )

def summarize_posterior_changes(alpha_prior, beta_prior, clicks, impressions):
    """
    Compares prior vs posterior means and returns a narrative.
    """
    alpha_post = alpha_prior + clicks
    beta_post = beta_prior + impressions - clicks
    prior_mean = alpha_prior / (alpha_prior + beta_prior)
    post_mean = alpha_post / (alpha_post + beta_post)
    delta = (post_mean - prior_mean) * 100
    return (
        f"After observing {clicks} clicks out of {impressions} impressions, "
        f"the estimated CTR shifts from {prior_mean:.2%} to {post_mean:.2%}, "
        f"an increase of {delta:.2f} percentage points."
    )
``` **Merge in Semantic Exploration**  
- Review your second notebook (`Semantics 050525.ipynb`) for narrative cells explaining priors.  
- Move reusable explanatory functions into a new module `semantics.py` and import them into `bayesian_ads.ipynb` as optional appendix cells.

