from typing import Dict, Any, Optional

from . import BaseConverter


class VlessConverter(BaseConverter):
    def convert(self, link: str, names: Dict[str, int]) -> Optional[Dict[str, Any]]:
        try:
            return self.handle_vshare_link(link, names)
        except Exception:
            return None
