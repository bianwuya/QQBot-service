from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    risk: str
    permissions: str
    parameters_schema: dict
    handler: object
    timeout: float = 2.0
    confirmation: bool = False


class Registry:
    def __init__(self):
        self.tools = {}

    def register(self, tool):
        if (not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', tool.name) or tool.name in self.tools
                or tool.risk not in ('L0','L1','L2','L3') or tool.permissions not in ('user','admin')
                or not 0 < tool.timeout <= 10 or not callable(tool.handler)):
            raise ValueError('invalid tool registration')
        self.tools[tool.name] = tool
        return tool

    def descriptors(self, admin=False, allow_l2=False):
        return [{'type':'function','function':{'name':t.name,'description':t.description,'parameters':t.parameters_schema}}
                for t in self.tools.values() if (t.risk=='L0' or (allow_l2 and admin and t.risk=='L2' and t.confirmation)) and (admin or t.permissions=='user')]
