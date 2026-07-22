# Research Priority

## Purpose

Turn the user's watchlist into a transparent order for evidence review. This is
research urgency, never investment attractiveness, expected return, or a trade
ranking.

## Required evidence

Use only the supplied `research_priority` packet. For every symbol, preserve:

- priority label and score;
- deterministic scoring components and their points;
- report/evidence timestamp;
- user thesis and next-review checks when available;
- missing-baseline status when a long-term report does not yet exist.

## Response protocol

1. Lead with which one or two symbols deserve review first and why.
2. Separate price abnormality, drawdown/volatility, evidence changes,
   fundamentals/cash flow, events, and data-coverage gaps.
3. Explain that a high urgency score can be caused by risk or missing evidence;
   it does not mean the stock is attractive.
4. Give concrete verification actions from `next_review`.
5. If a component is absent, do not invent it or substitute model memory.

## Hard boundaries

- Never translate priority into buy/sell/hold, position size, target price, stop
  loss, win rate, or future return probability.
- Never call the score a stock score, recommendation score, or expected-return
  score.
- Never rank by model preference or general market knowledge.
- Always state that the order is for research review only.
