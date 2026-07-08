import csv
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, Optional

from app.log import logger


class DiscRemuxer:
    """蓝光/光盘源自动化重封装处理器。"""

    _TINFO_DURATION_INDEX: int = 8

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None

    def terminate(self, timeout: int = 10) -> None:
        process = self._process
        if not process or process.poll() is not None:
            return
        logger.info(f"正在终止 MakeMKV 进程: pid={process.pid}")
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning(f"MakeMKV 进程未在 {timeout} 秒内退出，强制终止: pid={process.pid}")
            process.kill()
            process.wait(timeout=5)

    def validate_environment(self) -> None:
        """检查 MakeMKV 是否可用，如果不存在则自动尝试编译安装。"""
        try:
            subprocess.run(["makemkvcon"], capture_output=True, check=False)
            logger.info("环境检查通过，makemkvcon 已安装。")
        except FileNotFoundError:
            logger.warning("未检测到 makemkvcon，正在尝试自动编译安装，这可能需要几分钟，请耐心等待...")
            self._install_makemkv()
        except Exception as e:
            raise RuntimeError(f"环境检查失败，详细信息: {e}")

    def _install_makemkv(self) -> None:
        script_path = Path(__file__).parent / "install_makemkv.sh"
        if not script_path.exists():
            raise RuntimeError(f"安装脚本丢失: {script_path}")

        try:
            process = subprocess.run(
                ["bash", str(script_path)],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info("MakeMKV 自动编译安装完成。")
            logger.debug(f"安装日志输出: {process.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"MakeMKV 自动安装失败:\n{e.stderr}")
            raise RuntimeError("MakeMKV 自动安装失败，请查看日志或尝试手动进入容器安装。")

    def _run_process(self, cmd: list[str], progress_callback: Optional[Callable[[int], None]] = None) -> str:
        output_lines = []
        last_progress = -1
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        try:
            if self._process.stdout:
                for line in self._process.stdout:
                    output_lines.append(line)
                    progress = self._parse_progress(line.strip())
                    if progress is not None and progress != last_progress:
                        last_progress = progress
                        if progress_callback:
                            progress_callback(progress)

            return_code = self._process.wait()
            output = "".join(output_lines)
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, cmd, stderr="".join(output_lines[-80:]).strip())
            return output
        finally:
            self._process = None

    def _extract_info(self, source_root: Path) -> Dict[int, Dict[int, str]]:
        cmd = ["makemkvcon", "--robot", "info", f"file:{source_root}"]
        logger.info(f"正在扫描原盘媒体信息: {source_root}")
        output = self._run_process(cmd)

        titles: Dict[int, Dict[int, str]] = {}
        for line in output.splitlines():
            if line.startswith("TINFO:"):
                row = next(csv.reader([line[6:]]))
                titles.setdefault(int(row[0]), {})[int(row[1])] = row[3]
        return titles

    @staticmethod
    def parse_duration(duration_str: str) -> int:
        try:
            h, m, s = map(int, duration_str.split(":"))
            return h * 3600 + m * 60 + s
        except (ValueError, AttributeError):
            return 0

    def _get_longest_title(self, titles: Dict[int, Dict[int, str]]) -> str:
        if not titles:
            raise RuntimeError("未能在该原盘中找到任何可提取的 Title。")
        target_title, _ = max(
            titles.items(),
            key=lambda item: self.parse_duration(item[1].get(self._TINFO_DURATION_INDEX, "00:00:00")),
        )
        return str(target_title)

    @staticmethod
    def _parse_progress(line: str) -> Optional[int]:
        if not line.startswith("PRGV:"):
            return None
        try:
            current, total, _ = [int(part) for part in line[5:].split(",")[:3]]
            if total <= 0:
                return None
            return max(0, min(100, int(current * 100 / total)))
        except Exception:
            return None

    @staticmethod
    def _find_generated_mkv(output_dir: Path, before: set[Path], started_at: float) -> Path:
        candidates = []
        for mkv_file in output_dir.glob("*.mkv"):
            if mkv_file in before or not mkv_file.is_file():
                continue
            try:
                stat = mkv_file.stat()
            except OSError:
                continue
            if stat.st_mtime >= started_at - 2:
                candidates.append((stat.st_mtime, stat.st_size, mkv_file))
        if not candidates:
            raise RuntimeError(f"处理完成，但未能找到 MakeMKV 新生成的 MKV 文件: {output_dir}")
        candidates.sort(reverse=True)
        return candidates[0][2]

    def remux_to_mkv(
        self,
        source_root_path: str,
        output_file_path: str,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> Path:
        """提取最长正片，先生成 partial 文件，成功后改名为最终 MKV。"""
        source_root = Path(source_root_path)
        output_file = Path(output_file_path)
        output_dir = output_file.parent
        partial_file = output_file.with_suffix(".partial.mkv")

        output_dir.mkdir(parents=True, exist_ok=True)
        if partial_file.exists():
            partial_file.unlink()

        titles = self._extract_info(source_root)
        target_title = self._get_longest_title(titles)
        logger.info(f"自动识别主正片 Title ID: {target_title}")

        before = set(output_dir.glob("*.mkv"))
        started_at = time.time()
        cmd = [
            "makemkvcon",
            "--robot",
            "mkv",
            f"file:{source_root}",
            target_title,
            output_dir.as_posix(),
        ]
        logger.info(f"开始执行 MakeMKV 重封装: source={source_root}, output_dir={output_dir}")

        self._run_process(cmd, progress_callback=progress_callback)

        generated_file = self._find_generated_mkv(output_dir, before, started_at)
        generated_file.rename(partial_file)
        partial_file.rename(output_file)
        logger.info(f"重封装完成: {output_file}")
        return output_file
