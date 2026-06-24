from pathlib import Path

MAX_DATA_SIZE = 200    #知识库最大数据读取条数（共有25000条数据，全量加载耗时较长）
BASE_DIR = Path(__file__).resolve().parent

sqlite_db_dir = BASE_DIR / "sqlite_db" / "funds.db"

if __name__ == '__main__':
    print(BASE_DIR)
    print((BASE_DIR/"env.py").exists())
