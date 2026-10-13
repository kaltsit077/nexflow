"""演示脚本：验证 runner 能正常拉起 Python 子进程并捕获输出。"""
import argparse
import time


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--times", type=int, default=3)
    args = p.parse_args()

    for i in range(1, args.times + 1):
        print(f"[hello_demo] step {i}/{args.times}", flush=True)
        time.sleep(0.5)
    print("[hello_demo] done", flush=True)


if __name__ == "__main__":
    main()
