# modules/roas_visualization.py
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import gamma
import os


def plot_roas_posterior(alpha_param, scale_param, label, show=True):
    """
    Plot the Gamma posterior PDF for ROAS.
    """
    # Determine x-axis range (0 to 3× mean)
    mean = scale_param * alpha_param
    x = np.linspace(0, mean * 3, 200)
    y = gamma.pdf(x, a=alpha_param, scale=scale_param)

    plt.figure(figsize=(8, 4))
    plt.plot(x, y, label=label)
    plt.title(f"ROAS Posterior for {label}")
    plt.xlabel('Return on Ad Spend (Revenue/Cost)')
    plt.ylabel('Density')
    plt.legend()
    if show:
        plt.show()
   


def save_roas_plot(alpha_param, scale_param, label, path):
    """
    Save the ROAS posterior plot as a PNG file.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    plot_roas_posterior(alpha_param, scale_param, label, show=False)
    plt.savefig(path, bbox_inches='tight')
