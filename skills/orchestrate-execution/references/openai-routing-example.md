# OpenAI routing batch example

This example uses generic placeholder files and a placeholder coordinator ID. Replace them with current local values. The paths must exist, and task IDs, objectives and context sent to OpenAI must be within the user's export approval.

```json
{
  "schema_version": 2,
  "coordinator_id": "00000000-0000-0000-0000-000000000000",
  "tasks": [
    {
      "id": "csv_export",
      "objective": "Implement the agreed CSV export in the existing exporter.",
      "context": "The column order and encoding are already approved. Preserve the import path.",
      "allowed_files": ["/path/to/project/src/exporter.py"],
      "checks": ["python -B -m unittest tests.test_exporter -v"],
      "authorized": true,
      "export_approved": true,
      "inputs_ready": true
    }
  ]
}
```

The booleans record current owner facts; setting them does not create authority. If there are prerequisites, unavailable inputs, a conflicting writer or no export grant, keep the task local as held or direct work.

Run a fresh eligible batch once:

```text
python -B routing_decisions.py run batch.json run-directory --summary
```

The helper sends only the eligible task ID, objective and context. It keeps file contents, local paths and checks local, fingerprints the allowed files, and saves the complete packet. Inspect its result and complete the runtime's normal readiness and dispatch steps. The helper does not launch the worker.

For the unchanged batch and tool identity, recreate the same packet locally:

```text
python -B routing_decisions.py emit batch.json run-directory --summary
```

This command makes no provider request. If the task or source changes materially, get a new local disposition. If the earlier request may have been submitted but its outcome is uncertain, reconcile that run; do not submit it again with a new ID.
