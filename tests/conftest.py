# 保证 CI 环境下也能从仓库根目录导入 app
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
