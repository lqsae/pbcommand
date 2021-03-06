import tempfile

from pbcommand.models.legacy import Pipeline


class TestLegacyModels:

    def test_load_pipeline_from_json(self):
        pipeline_json = """
{
  "_comment": "Automatically generated by pbcromwell.wdl2json",
  "description": "Cromwell workflow dev_diagnostic_subreads",
  "entryPoints": [
    {
      "entryId": "eid_subread",
      "fileTypeId": "PacBio.DataSet.SubreadSet",
      "name": "Entry eid_subread",
      "optional": false
    },
    {
      "entryId": "eid_ref_dataset",
      "fileTypeId": "PacBio.DataSet.ReferenceSet",
      "name": "Entry eid_ref_dataset",
      "optional": true
    }
  ],
  "id": "cromwell.workflows.dev_diagnostic_subreads",
  "name": "SubreadSet Diagnostics Workflow",
  "options": [],
  "schemaVersion": "2.0.0",
  "tags": [
    "dev",
    "cromwell"
  ],
  "taskOptions": [
    {
      "default": 0,
      "description": "Cromwell workflow option exit_code",
      "id": "exit_code",
      "name": "Exit code",
      "optionTypeId": "integer"
    },
    {
      "default": false,
      "description": "Cromwell workflow option emit_warn_alarm",
      "id": "emit_warn_alarm",
      "name": "Emit warn alarm",
      "optionTypeId": "boolean"
    },
    {
      "default": false,
      "description": "Cromwell workflow option emit_error_alarm",
      "id": "emit_error_alarm",
      "name": "Emit error alarm",
      "optionTypeId": "boolean"
    }
  ],
  "version": "0.5.0"
}"""
        json_file = tempfile.NamedTemporaryFile(suffix=".json").name
        with open(json_file, "w") as json_out:
            json_out.write(pipeline_json)
        p = Pipeline.load_from_json(json_file)
        assert p.pipeline_id == "cromwell.workflows.dev_diagnostic_subreads"
        s = p.summary()
