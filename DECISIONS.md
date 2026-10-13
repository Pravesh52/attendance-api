# DECISIONS.md

1. **Indexes.** On attendance_logs: unique (emp_code, date) enforces one record per day; (date desc, emp_code) serves sorted lists and the leaderboard; (emp_code, punch_in desc) finds the record to close; (status, date, emp_code) serves status filters. On employees: unique emp_code, (department, joined_on), and joined_on for the summary. I rejected indexing late_minutes: the date range already narrows each scan.

2. **Punch-in race.** Both requests call insert_one. The unique (emp_code, date) index lets one succeed; the other raises DuplicateKeyError, which I return as 409. I dropped find-then-insert because both could pass it together.

3. **Ties.** Tied employees share a rank (1, 2, 2, 4). I filter rank <= limit after ranking, so a tie at the cutoff returns every tied employee and the list can exceed limit.

4. **Headcount.** The summary starts from employees, not logs. A lookup attaches each person's logs and unwind keeps people with none, so everyone who joined by month end is counted.

5. **100x data.** I would keep pre-aggregated monthly totals in a separate collection, updated on each punch or correction, so analytics read small documents instead of scanning all logs.