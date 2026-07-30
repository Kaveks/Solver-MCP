"""
mcp_server/schemas — Pydantic input models for the solver tools (Layer 2).

One model per solver. Re-exported here so callers can import from the package:

    from mcp_server.schemas import OpenFOAMInput
"""

from mcp_server.schemas.freecad import FreecadInput
from mcp_server.schemas.lammps import LAMMPSInput
from mcp_server.schemas.openfoam import OpenFOAMInput

__all__ = ["OpenFOAMInput", "LAMMPSInput", "FreecadInput"]
