"""Unit tests for CurrentTimeTool - the reference BaseTool implementation."""

from core.agent.tools.current_time_tool import CurrentTimeTool


def test_schema_has_no_required_parameters():
    tool = CurrentTimeTool()
    assert tool.parameters["required"] == []


def test_defaults_to_utc_when_no_timezone_given():
    tool = CurrentTimeTool()
    result = tool.execute()
    assert "(UTC)" in result


def test_uses_requested_timezone():
    tool = CurrentTimeTool()
    result = tool.execute(timezone="Asia/Ho_Chi_Minh")
    assert "(Asia/Ho_Chi_Minh)" in result


def test_unknown_timezone_returns_error_string_not_raise():
    tool = CurrentTimeTool()
    result = tool.execute(timezone="Not/AZone")
    assert "Error" in result
    assert "Not/AZone" in result


def test_to_openai_schema_shape():
    tool = CurrentTimeTool()
    schema = tool.to_openai_schema()
    assert schema == {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
