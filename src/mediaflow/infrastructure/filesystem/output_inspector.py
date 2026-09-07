"""Local final-output inspection adapter."""

from mediaflow.domain import OutputPath


class LocalOutputFileInspector:
    def exists(self, output_path: OutputPath) -> bool:
        try:
            return output_path.value.is_file() and output_path.value.stat().st_size > 0
        except OSError:
            return False

    def remove(self, output_path: OutputPath) -> bool:
        """Remove only the exact final file named by a confirmed application command."""

        try:
            if not output_path.value.is_file():
                return False
            output_path.value.unlink()
            return True
        except OSError:
            return False
