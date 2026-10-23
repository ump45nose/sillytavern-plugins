"""配置分层和严格校验测试。"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from review.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    """验证未知配置、必填项和功能开关。"""

    def _env(self, root: Path, extra: str = "") -> Path:
        """生成不含真实凭据的完整测试 ENV。"""

        template = (Path(__file__).parents[1] / ".env.example").read_text(encoding="utf-8")
        values = []
        for line in template.splitlines():
            if line.startswith("REVIEW_") and "=" in line:
                key = line.split("=", 1)[0]
                if key == "REVIEW_MEMOS_BASE_URL":
                    values.append(f"{key}=http://127.0.0.1:5230")
                elif key.startswith("REVIEW_ENABLE_"):
                    values.append(line)
                elif key.endswith(("_ROOT", "_FILE", "_DB", "_DIR", "_SPOOL", "_MD")):
                    values.append(f"{key}={root / key.lower()}")
                else:
                    values.append(line)
        path = root / ".env"
        path.write_text("\n".join(values) + "\n" + extra, encoding="utf-8")
        return path

    def test_valid_configuration(self) -> None:
        """完整 ENV 与受支持 YAML 应成功加载。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_config(self._env(root), Path(__file__).parents[1] / "config/review.yaml")
            self.assertEqual(config.policy["schema_version"], 1)
            self.assertFalse(config.flags.daily)

    def test_unknown_review_env_is_rejected(self) -> None:
        """未知 REVIEW_ 变量必须阻止启动。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ConfigError):
                load_config(self._env(root, "REVIEW_TYPO=true\n"), Path(__file__).parents[1] / "config/review.yaml")

    def test_unknown_nested_policy_is_rejected(self) -> None:
        """嵌套策略拼写错误必须由 JSON Schema 阻止。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = Path(__file__).parents[1] / "config/review.yaml"
            policy = yaml.safe_load(source.read_text(encoding="utf-8"))
            policy["daily"]["silent_default"] = True
            config_dir = root / "config"
            schema_dir = root / "schemas"
            config_dir.mkdir()
            schema_dir.mkdir()
            target = config_dir / "review.yaml"
            target.write_text(yaml.safe_dump(policy, allow_unicode=True), encoding="utf-8")
            schema_source = Path(__file__).parents[1] / "schemas/review.schema.json"
            (schema_dir / "review.schema.json").write_text(schema_source.read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(self._env(root), target)

    def test_conflicting_schedule_is_rejected(self) -> None:
        """ENV 与 YAML 的同一调度不一致时必须阻止启动。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ConfigError):
                load_config(
                    self._env(root, "REVIEW_DAILY_TIME=22:00\n"),
                    Path(__file__).parents[1] / "config/review.yaml",
                )


if __name__ == "__main__":
    unittest.main()
