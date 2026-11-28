# Bayesian Marketing Analysis & Reporting Template

This project uses Bayesian statistics to analyze marketing campaign data from Meta, Google, and LinkedIn. It automatically generates a comprehensive PDF report with performance summaries, posterior distributions, and model diagnostics.

## Features

-   Connects directly to platform APIs to fetch the latest data.
-   Calculates posteriors for CTR, CVR, CPA, and ROAS.
-   Uses OpenAI's GPT to generate narrative performance summaries.
-   Generates a clean, client-ready PDF report.

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <your-repo-url>
    cd <your-repo-name>
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure Credentials:**
    Create a `.env` file in the root directory and populate it with your API keys. A template is shown below:
    ```
    # .env file
    META_APP_ID="YOUR_META_APP_ID_GOES_HERE"
    META_APP_SECRET="YOUR_META_APP_SECRET_GOES_HERE"
    # ...add all other keys here...
    ```

## How to Run

After setting up the environment, run the main Jupyter Notebook:
```
jupyter notebook bayesian_ads.ipynb
```
Execute the cells in order. The final report will be generated in the `outputs/` folder (which is created automatically).