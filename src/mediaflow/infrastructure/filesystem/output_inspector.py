"""Local final-output inspection adapter."""

from mediaflow.domain import OutputPath


class LocalOutputFileInspector:
    def exists(self, output_path: OutputPath) -> bool:
        try:
            return output_path.value.is_file() and output_path.value.stat().st_size > 0
        except OSError:
            return False
