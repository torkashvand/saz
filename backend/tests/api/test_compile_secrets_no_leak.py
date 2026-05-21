"""Compile errors must not echo back template helper values verbatim.

The DSL allows `{{ $secret('NAME') }}` references in step params. If a flow
is invalid for an unrelated reason, the compile-error message should still
not leak any literal secret name in a way the UI would render as plaintext.

This test pins the current behavior: compile errors contain the credential
reference token (which only mentions the NAME), never the resolved value
(which the compiler never sees anyway). It's a regression gate against
future error-message refactors that might log the resolved environment.
"""

from __future__ import annotations

import textwrap


def test_compile_error_does_not_include_environment_or_credential_values(
    app_client, monkeypatch
) -> None:
    monkeypatch.setenv("SAZ_TEST_SECRET", "supersecret-value-do-not-leak")

    bad_yaml = textwrap.dedent(
        """\
        schema_version: 1
        flow:
          name: demo
          description: ok
        credentials:
          uses: [api_token]
        workflow:
          planner_mode: deterministic
          steps:
            - id: bad_step
              type: tool.call
              tool: http_request
              params:
                url: "{{ $secret('api_token') }}"
        """
    )

    response = app_client.post("/api/v1/flows/compile", json={"yaml": bad_yaml})
    assert response.status_code == 200
    body = response.json()
    # Description is missing for tool.call, so validation should fail.
    assert body["valid"] is False
    serialized = response.text
    assert "supersecret-value-do-not-leak" not in serialized
