# modules/diagnostics.py
import numpy as np
from scipy.stats import invgamma, gamma


def sample_beta_posterior(alpha, beta, size=1000):
    """
    Draw samples from a Beta(alpha, beta) posterior distribution.

    Returns:
      - NumPy array of draws
    """
    return np.random.beta(alpha, beta, size)


def sample_inv_gamma_posterior(alpha, beta, size=1000):
    """
    Draw samples from an Inverse-Gamma(alpha, scale=beta) posterior.

    Returns:
      - NumPy array of draws
    """
    return invgamma.rvs(alpha, scale=beta, size=size)


def sample_gamma_posterior(alpha, scale, size=1000):
    """
    Draw samples from a Gamma(alpha, scale=scale) posterior.

    Returns:
      - NumPy array of draws
    """
    return gamma.rvs(alpha, scale=scale, size=size)

