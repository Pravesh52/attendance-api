# DECISIONS.md  (about 150-200 words in total - plain language, your own words)

1. **Indexes.** Which indexes did you create, and which query or guarantee does each one serve? Which one did you consider and reject?
2. **Punch-in race.** Two identical punch-in requests arrive at the same instant. Walk through exactly what happens in your code.
3. **Ties.** Two employees are tied on late minutes at the cutoff of `limit`. What does your leaderboard return, and why?
4. **Headcount.** How does your department summary make sure employees with zero logs are counted?
5. **One thing you would change** if this had to serve 100x the data.


# DECISIONS.md

1. **Indexes.** A unique index on (emp_code, date) guarantees one record per day and serves per-employee queries. (date desc, emp_code) serves the sorted attendance list, and (emp_code, punch_in desc) finds the record to close on punch-out. I rejected a lone index on status: with only five values it filters almost nothing.

2. **Punch-in race.** Both requests reach insert_one. The unique (emp_code, date) index lets exactly one succeed, and the other raises DuplicateKeyError, which I return as a 409. I dropped the find-then-insert check because both requests could pass it at the same moment.

3. **Ties.** Ranking is standard competition ranking, so tied employees share a rank. I return every row whose rank is within the limit, so the list can be longer than the limit instead of cutting a tie arbitrarily.

4. **Headcount.** The summary starts from employees, not from logs. A lookup attaches each person's logs, and unwind keeps people who have none, so headcount counts everyone who joined by the end of the month.

5. **One change for 100x data.** I would pre-aggregate monthly totals into a separate collection, updated on each punch or correction, so analytics read small summary documents instead of scanning all logs.
