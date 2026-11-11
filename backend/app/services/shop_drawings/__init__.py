"""Shop drawings generation — DXF via ezdxf, PDF export via matplotlib backend.

Stage 1: pipeline + title block + blank drawing area. Stage 2 adds front/side
elevation geometry; Stage 3 adds variants + BOM.
"""

from .framing import generate_framing_drawing
from .spec import build_door_spec, build_spec_from_config

__all__ = ["generate_framing_drawing", "build_door_spec", "build_spec_from_config"]
