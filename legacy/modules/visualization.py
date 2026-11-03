import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import beta as beta_dist
import os

def plot_posterior(alpha_param, beta_param, ad_name, show=True):
    """
    Plot the Beta posterior distribution interactively.

    Parameters:
    - alpha_param: int or float, alpha of the Beta distribution
    - beta_param: int or float, beta of the Beta distribution
    - ad_name: str, label for the plot
    - show: bool, whether to call plt.show()
    """
    x = np.linspace(0, 1, 200)
    y = beta_dist.pdf(x, alpha_param, beta_param)
    plt.figure(figsize=(8, 4))
    plt.plot(x, y, label=f"{ad_name}")
    plt.title(f"Posterior for {ad_name}")
    plt.xlabel('CTR')
    plt.ylabel('Density')
    plt.legend()
    if show:
        plt.show()
    plt.close()

def save_posterior_plot(alpha_param, beta_param, ad_name, path):
    """
    Plot the Beta posterior distribution and save it as a PNG.

    Parameters:
    - alpha_param: int or float, alpha of the Beta distribution
    - beta_param: int or float, beta of the Beta distribution
    - ad_name: str, label for the file name and plot legend
    - path: str, full path including filename.png where to save
    """
    # Ensure the output directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Generate the plot
    x = np.linspace(0, 1, 200)
    y = beta_dist.pdf(x, alpha_param, beta_param)
    plt.figure(figsize=(8, 4))
    plt.plot(x, y, label=f"{ad_name}")
    plt.title(f"Posterior for {ad_name}")
    plt.xlabel('CTR')
    plt.ylabel('Density')
    plt.legend()

    # Save to file
    plt.savefig(path, bbox_inches='tight')
    plt.close()
