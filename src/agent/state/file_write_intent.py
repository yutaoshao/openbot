"""Deterministic classification for file-write commands and discussion."""

from __future__ import annotations

import re
from enum import Enum, auto

_FILE_WRITE_ACTION = r"(?:保存|写入|追加|补上|存到|加到|\bsave\b|\bwrite\b|\bappend\b)"
_FILE_WRITE_ACTION_PATTERN = re.compile(_FILE_WRITE_ACTION, re.IGNORECASE)
_FILE_WRITE_REQUEST_PATTERN = re.compile(
    rf"^(?!请问)(?:(?:(?:你)?(?:可以|能不能|可不可以|能否|能)\s*(?:帮我|帮忙)?|"
    rf"请(?:你)?|帮我|帮忙|麻烦(?:你)?|记得|需要你|你要|还要|我要|我想|"
    rf"给我|替我|务必|\b(?:please|can you|could you|would you)\b)\s*)+"
    rf"(?:(?:帮我|帮忙|替我|给我|先|再|然后|重新|继续|也)\s*|"
    rf"(?:使用|用)\s+\S+\s*)*(?:{_FILE_WRITE_ACTION}|(?:把|将).*{_FILE_WRITE_ACTION})",
    re.IGNORECASE,
)
_FILE_WRITE_CONNECTOR_PATTERN = re.compile(
    rf"^(?:(?:先|然后|再|接着|随后|最后|现在|重新|继续|也|并且|并|同时|顺便)\s*)+"
    rf"{_FILE_WRITE_ACTION}",
    re.IGNORECASE,
)
_FILE_WRITE_TOOL_COMMAND_PATTERN = re.compile(
    rf"^(?:使用|用)\s+\S+\s*{_FILE_WRITE_ACTION}", re.IGNORECASE
)
_FILE_WRITE_NEGATED_REQUEST_PATTERN = re.compile(
    r"^(?:(?:请(?:你)?|麻烦(?:你)?|please)\s*)?"
    r"(?:不要|不用|无需|不必|禁止|别|不想|不需要|不应|不准|不能|do not|don't|never)",
    re.IGNORECASE,
)
_FILE_WRITE_DIRECT_NEGATION_PATTERN = re.compile(
    r"(?:不要|不用|无需|不必|禁止|别|不想|不需要|不应|不准|不|没有|没|未|"
    r"do not|don't|never)\s*$",
    re.IGNORECASE,
)
_FILE_WRITE_STATUS_QUESTION_PATTERN = re.compile(
    rf"{_FILE_WRITE_ACTION}.*(?:了吗|了么|了没|过吗|成功吗|完成吗|好了吗)\s*[?？]?$",
    re.IGNORECASE,
)
_FILE_WRITE_INFO_QUESTION_PATTERN = re.compile(
    r"(?:什么|哪里|哪儿|在哪(?:里|儿)?|为何|为什么|怎么|如何|是否|是不是|有没有|"
    r"\b(?:what|which|why|how)\b).*?[?？]?$",
    re.IGNORECASE,
)
_FILE_WRITE_NOUN_PATTERN = re.compile(
    rf"^{_FILE_WRITE_ACTION}(?:位置|路径|目录|工具|方式|状态|结果|记录|错误|问题)"
)
_INLINE_QUOTED_TEXT_PATTERN = re.compile(r"“[^”]*”|\"[^\"]*\"|'[^']*'")
_FILE_WRITE_CLAUSE_SPLIT_PATTERN = re.compile(r"(?<=[。！？?；;])|[,，\n]")


class FileWriteIntent(Enum):
    """Trusted deterministic classification of the current file-write intent."""

    COMMAND = auto()
    DISCUSSION = auto()
    UNSPECIFIED = auto()


def classify_trusted_file_write_intent(text: str) -> FileWriteIntent:
    """Classify text after untrusted blocks and payload have been removed."""
    intents = tuple(
        _file_write_clause_intent(clause) for clause in _FILE_WRITE_CLAUSE_SPLIT_PATTERN.split(text)
    )
    if FileWriteIntent.COMMAND in intents:
        return FileWriteIntent.COMMAND
    if FileWriteIntent.DISCUSSION in intents:
        return FileWriteIntent.DISCUSSION
    return FileWriteIntent.UNSPECIFIED


def contains_file_write_action(text: str) -> bool:
    return _FILE_WRITE_ACTION_PATTERN.search(text) is not None


def _file_write_clause_intent(clause: str) -> FileWriteIntent:
    unquoted = _INLINE_QUOTED_TEXT_PATTERN.sub(" ", clause)
    command_prefix = unquoted.strip().lower().lstrip("0123456789.、) ")
    action_matches = tuple(_FILE_WRITE_ACTION_PATTERN.finditer(command_prefix))
    if not action_matches:
        return FileWriteIntent.UNSPECIFIED
    if _write_action_is_negated(command_prefix, action_matches[-1].start()):
        return FileWriteIntent.DISCUSSION
    if _FILE_WRITE_STATUS_QUESTION_PATTERN.search(command_prefix) is not None:
        return FileWriteIntent.DISCUSSION
    if _FILE_WRITE_INFO_QUESTION_PATTERN.search(command_prefix) is not None:
        return FileWriteIntent.DISCUSSION
    if _FILE_WRITE_NOUN_PATTERN.search(command_prefix) is not None:
        return FileWriteIntent.DISCUSSION
    if _is_explicit_write_command(command_prefix):
        return FileWriteIntent.COMMAND
    return FileWriteIntent.UNSPECIFIED


def _write_action_is_negated(clause: str, action_start: int) -> bool:
    if _FILE_WRITE_NEGATED_REQUEST_PATTERN.search(clause) is not None:
        return True
    return _FILE_WRITE_DIRECT_NEGATION_PATTERN.search(clause[:action_start]) is not None


def _is_explicit_write_command(clause: str) -> bool:
    return (
        any(
            pattern.search(clause) is not None
            for pattern in (
                _FILE_WRITE_REQUEST_PATTERN,
                _FILE_WRITE_CONNECTOR_PATTERN,
                _FILE_WRITE_TOOL_COMMAND_PATTERN,
            )
        )
        or clause.startswith(("把", "将"))
        or _FILE_WRITE_ACTION_PATTERN.match(clause) is not None
    )
