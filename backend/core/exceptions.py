# backend/core/exceptions.py
# 项目统一异常体系:早暴露、可分类、可降级。


class HealthAssistantError(Exception):
    """项目基础异常:所有自定义异常都从这里派生。"""


class LLMAPIError(HealthAssistantError):
    """模型调用失败(超时/限流/空正文等)。"""


class ToolError(HealthAssistantError):
    """MCP 工具体系失败(连接/超时/业务拒绝)。"""


class A2AError(HealthAssistantError):
    """A2A 下游 Agent 调用失败。"""


class InvalidInputError(HealthAssistantError):
    """输入非法(参数校验不过)——不可重试。"""


class AuthenticationError(HealthAssistantError):
    """认证/鉴权失败——不可重试。"""


class QueryNeedsMoreInfo(HealthAssistantError):
    """缺参追问:这是正常业务态,不是失败(Agent 返回 INPUT_REQUIRED 语义)。"""
