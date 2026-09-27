import logging
import os
import sys


def get_logger(name: str = "LIGHT") -> logging.Logger:
    """Configure and return a standard library logger."""
    logger = logging.getLogger(name)

    if not logger.handlers:
        level_name = os.environ.get("LIGHT_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        logger.setLevel(level)
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False

    return logger


logger = get_logger()


def log_info(message: str):
    logger.info(f"[LIGHT] {message}")


def log_debug(message: str):
    logger.debug(f"[DEBUG] {message}")


def log_warning(message: str):
    logger.warning(f"[WARN] {message}")


def log_voice(message: str):
    logger.info(f"[VOICE] {message}")


def log_laya(message: str):
    logger.info(f"[LAYA] {message}")


def log_command(message: str):
    logger.info(f"[COMMAND] {message}")


def log_executor(message: str):
    logger.info(f"[EXECUTOR] {message}")


def log_browser(message: str):
    logger.info(f"[BROWSER] {message}")


def log_state(message: str):
    logger.info(f"[STATE] {message}")


def log_perf(message: str):
    logger.info(f"[PERF] {message}")


def log_llm(message: str):
    logger.info(f"[LLM] {message}")


def log_error(message: str):
    logger.error(f"[ERROR] {message}")

