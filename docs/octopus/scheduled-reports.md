# Scheduled reports

A scheduled report is an agent task with a task specific dashboard conversation.
In the task editor choose **Daily report**. The scheduler still determines when
the task runs, so the interval can be changed.

Two settings are independent:

- **Create a new conversation for each report** controls presentation. Turn it
  off to append all reports for the task to one conversation.
- **Use previous reports as context** controls the information supplied to the
  model. When enabled, choose one to 30 successful reports. The default is one.

The model runs with a separate execution context for each report. With previous
reports disabled, earlier conversations are not automatically injected. The
expert's memory and tools can still access information according to their normal
permissions. Failed or cancelled runs are not included as previous successes.

Task owners can configure these options in the dashboard or API. An expert can
set `report_mode`, `report_new_conversation`, `report_include_previous` and
`report_previous_count` using the cron management tools. If the expert created
the task from an IM conversation, completed reports are also sent to that
original channel. Existing task schedules and old conversations are unchanged
until their owner edits the task.

For the offline CLI use `octop cron create --daily-report` with the existing
`--fresh-thread` flag if each report should have its own conversation. Add
`--include-previous-reports --previous-report-count N` to include history.
Restart the running server after offline CLI changes, as for other cron jobs.

The API accepts `report_options` with `new_conversation`, `include_previous` and
`previous_count`. Send `null` when changing a report back to an ordinary task.
An omitted field on a PATCH preserves its current value.
