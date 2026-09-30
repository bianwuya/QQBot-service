"""Small closed JSON Schema subset used by this fixed registry."""


def validate(schema, value):
    kind = schema.get('type')
    if kind == 'object':
        if not isinstance(value, dict):
            return False
        props = schema.get('properties', {})
        if set(value)-set(props) or not set(schema.get('required', ())) <= set(value):
            return False
        return all(validate(props[k], v) for k, v in value.items())
    if kind == 'string':
        return (isinstance(value, str) and schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 200)
                and ('enum' not in schema or value in schema['enum']))
    if kind == 'integer':
        return type(value) is int and schema.get('minimum', 0) <= value <= schema.get('maximum', 100)
    if kind == 'boolean':
        return type(value) is bool
    return False


def object_schema(properties=None, required=()):
    return {'type':'object', 'properties':properties or {}, 'required':list(required), 'additionalProperties':False}
