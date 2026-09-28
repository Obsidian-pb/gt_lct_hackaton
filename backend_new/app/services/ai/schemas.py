"""Explicit output contracts shared by generation and provider adapter."""
TEXT = {'type': 'string'}


def obj(**properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def task_schema(fields):
    field = obj(truth=TEXT, known=TEXT, expected=TEXT, criterion=TEXT, weight={'type': 'integer', 'minimum': 1, 'maximum': 10})
    return obj(title=TEXT, opening=TEXT, persona=TEXT, fields=obj(**{key: field for key in fields}))


def assessment_schema(fields, verdicts):
    row = obj(verdict={'type': 'string', 'enum': list(verdicts)}, comment=TEXT, clarification=TEXT,
              evidence={'type': 'array', 'items': obj(turn_id={'type': 'integer'}, quote=TEXT)})
    return obj(summary=TEXT, fields=obj(**{key: row for key in fields}))
