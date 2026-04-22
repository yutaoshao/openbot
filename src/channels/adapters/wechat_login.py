"""CLI for logging a WeChat personal account into the iLink adapter."""

from __future__ import annotations

import argparse
import asyncio

from src.core.config import load_config

from .wechat_ilink_api import DEFAULT_ILINK_BOT_TYPE, WeChatIlinkClient
from .wechat_state import WeChatStateStore

_LOGIN_TIMEOUT_SECONDS = 8 * 60


async def _run_login(config_path: str, timeout_seconds: int) -> int:
    config = load_config(config_path)
    store = WeChatStateStore(config.wechat.state_path)
    client = WeChatIlinkClient(config.wechat.api_base_url)
    await client.start()
    try:
        qr = await client.fetch_login_qrcode(bot_type=DEFAULT_ILINK_BOT_TYPE)
        png_path = store.login_png_path()
        _save_login_qr_png(qr["qrcode_img_content"], png_path)
        print(f"WeChat QR content: {qr['qrcode_img_content']}")
        print(f"WeChat QR image saved to: {png_path}")
        base_url = config.wechat.api_base_url
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            status = await client.poll_login_status(
                qrcode=qr["qrcode"],
                base_url=base_url,
            )
            login_state = status.get("status", "wait")
            if login_state == "wait":
                await asyncio.sleep(1.0)
                continue
            if login_state == "scaned":
                print("二维码已扫码，请在微信里确认。")
                await asyncio.sleep(1.0)
                continue
            if login_state == "scaned_but_redirect":
                redirect_host = status.get("redirect_host")
                if not redirect_host:
                    raise RuntimeError("扫码重定向时未返回 redirect_host。")
                base_url = redirect_host.rstrip("/")
                print(f"检测到登录节点切换，改用 {base_url} 继续轮询。")
                continue
            if login_state == "expired":
                raise RuntimeError("二维码已过期，请重新运行登录命令。")
            if login_state == "confirmed":
                account_id = str(status.get("ilink_bot_id", "")).strip()
                bot_token = str(status.get("bot_token", "")).strip()
                if not account_id or not bot_token:
                    raise RuntimeError("登录成功但 iLink 未返回完整账号信息。")
                state = store.save_login(
                    account_id=account_id,
                    bot_token=bot_token,
                    api_base_url=base_url,
                    user_id=str(status.get("ilink_user_id", "")).strip(),
                )
                print(f"微信登录成功，账号已保存到 {store.path}")
                print(f"account_id={state.account_id}")
                return 0
            raise RuntimeError(f"未知二维码状态: {login_state}")
        raise RuntimeError("等待扫码登录超时。")
    finally:
        await client.stop()


def _save_login_qr_png(qr_content: str, png_path) -> None:
    import qrcode

    png_path.parent.mkdir(parents=True, exist_ok=True)
    image = qrcode.make(qr_content)
    image.save(png_path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Login to WeChat iLink for OpenBot.")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the OpenBot config file.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=_LOGIN_TIMEOUT_SECONDS,
        help="How long to wait for the QR code to be confirmed.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    return asyncio.run(_run_login(args.config, args.timeout_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
