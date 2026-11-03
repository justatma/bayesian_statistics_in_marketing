# modules/cpa_visualization.py
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import invgamma
import os


def plot_cpa_posterior(alpha_param, beta_param, label, show=True):
    """
    Plot the Inverse-Gamma posterior PDF for CPA.

    Parameters:
    - alpha_param: shape of posterior (α)
    - beta_param: scale of posterior (β)
    - label: legend label (e.g., 'Ad A CPA')
    - show: whether to call plt.show()
    """
    # Determine x-axis range: 0 to mean*3
    mean = beta_param / (alpha_param - 1) if alpha_param > 1 else beta_param
    x = np.linspace(0, mean * 3, 200)
    y = invgamma.pdf(x, a=alpha_param, scale=beta_param)

    plt.figure(figsize=(8, 4))
    plt.plot(x, y, label=label)
    plt.title(f"CPA Posterior for {label}")
    plt.xlabel('Cost per Acquisition (USD)')
    plt.ylabel('Density')
    plt.legend()
    if show:
        plt.show()
 


def save_cpa_plot(alpha_param, beta_param, label, path):
    """
    Save the CPA posterior plot as a PNG file.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Draw without showing
    plot_cpa_posterior(alpha_param, beta_param, label, show=False)
    plt.savefig(path, bbox_inches='tight')
