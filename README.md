Notre Dame Trading Competition – Case Studies

This repository contains my submissions for the University of Notre Dame Trading Competition, consisting of:
1) An algorithmic trading case focused on ETF basket market-making on the DELTA Exchange.
2) A manual trading case based on historical price analysis.

The project demonstrates systematic trading design, market microstructure awareness, and disciplined risk management under realistic exchange constraints.

Repository Structure
.
├── Case 1 - Algorithmic Trading/
│   ├── src/
│   │   └── delta_bot/
│   │       ├── strategy.py
│   │       ├── order_manager.py
│   │       ├── risk.py
│   │       └── quote_engine.py
│   ├── pyproject.toml
│   └── README.md
│
└── Case 2 - Manual Trading/
    ├── analysis.py
    └── prices.csv

Case 1 – Algorithmic Trading (DELTA Exchange)

A maker-only market-making algorithm developed for the DELTA Exchange environment used in the Notre Dame Trading Competition.

Core Design
- Quotes ETF basket using a synthetic fair value
- Maker-only execution (never crosses the spread)
- Multi-level bid/ask ladders
- Inventory-aware skewing to manage directional risk
- Volatility-adjusted spreads and sizing
- Strict enforcement of exchange rate limits
- Conservative risk controls on inventory and exposure

Code Overview

- strategy.py – Trading logic, fair-value computation, and fill handling
- quote_engine.py – Construction of layered quotes around fair value
- order_manager.py – Order lifecycle management and efficient updates
- risk.py – Inventory limits, exposure caps, and throttling logic

Further implementation details are provided in
📄 Case 1 - Algorithmic Trading/README.md.

Case 2 – Manual Trading

A discretionary trading case built on historical market data.

Components

- prices.csv – Provided price data
- analysis.py – Analysis and trade decision framework

Focus areas:

- Identifying trends and inefficiencies
- Constructing trades based on price behaviour
- Evaluating outcomes retrospectively

Technologies Used

- Python 3.10+
- DELTA Exchange competition framework
- NumPy / Pandas (manual trading analysis)

Competition Context

This repository was developed exclusively for the University of Notre Dame Trading Competition and adheres to the rules, constraints, and simulated market conditions specified by the organizers.

Disclaimer

This project is for educational and competition purposes only and is not intended for live trading.
