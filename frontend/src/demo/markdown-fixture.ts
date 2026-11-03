// Synthetic reproduction of Chinese emphasis and reference links; URLs are placeholders.
export const markdownReply = `**先选 KIPRUN RUN500 的“轻薄透气款跑步袜”，买两双试穿就够。**它比较符合你穿网面运动鞋、希望减少闷湿的需求。

挑选时按这个顺序：

- **首选：RUN500 薄款 / 轻薄款。** 我查到官方有“轻薄透气中筒跑步袜，两双装”，脚背有透气区域。[官方款式参考](https://example.com/run500)。国内名称、货号可能不同。
- **备选：薄款美利奴羊毛混纺袜。** 如果你更在意味道，可以买一双对比。
- **暂不优先：厚毛圈、加厚缓震、冬季保暖徒步袜。** 你主要是日常通勤，不需要为了缓震增加厚度。

**特别注意：RUN500 同时有薄款和厚款，不能只按数字选。**要看商品详情中的厚度、材质和透气设计。

参考：[迪卡侬袜子系列](https://example.com/socks)、[Smartwool 日常袜说明](https://example.com/smartwool)。

中英文混排：**重要提示（Important Note）：**请按实际穿着感受选择。*轻薄（非加厚）。*这是斜体。~~厚款（旧建议）。~~这是删除线。

嵌套链接：**参考[款式说明](https://example.com/details)。**继续阅读。裸链接：https://example.com/product。这句不属于网址。

行内代码保留星号：\`**literal**\`。

\`\`\`text
**代码里的星号保持原样。**
\`\`\`

\`\`\`markdown
# 本周计划

- **保留 Markdown 原文**
- 点击右上角复制按钮
\`\`\`

\`\`\`python
def greet(name):
    return f"你好，{name}"

print(greet("OpenBot"))
\`\`\`

\`\`\`
没有语言标记的文本块也可以复制。
GET https://example.com/reports?workspace=qinghe-design-week&format=markdown&include=participants,materials,venue,owners,next-actions&language=zh-CN
\`\`\`

| 款式 | 用途 |
| --- | --- |
| 轻薄款 | 日常通勤 |
| 加厚款 | 寒冷天气 |

宽表格：

| 款式 | 材质 | 厚度 | 通勤 | 运动 | 保暖 | 选购说明 |
| --- | --- | --- | --- | --- | --- | --- |
| 轻薄款 | 混纺 | 薄 | 适合 | 适合 | 较弱 | 日常穿网面运动鞋时，优先试穿并观察脚底是否潮湿，再决定是否需要其他材质。 |
| 加厚款 | 羊毛混纺 | 厚 | 按需 | 按需 | 较强 | 适合寒冷天气，日常通勤需要结合鞋内空间和实际温度判断。 |`;
