# Clash Rule Provider

**Clash Rule Provider** 生成适用于 [Meta Kernel](https://github.com/MetaCubeX/mihomo/tree/Meta) 定制配置，便于增加、修改和删除规则。

- 即时通知 Clash 刷新规则集合
- 基于 Meta 内核丰富的代理组配置，提供灵活的路由功能
- 支持按大洲分组节点
- GEO 规则输入提示
- 支持 [ACL4SSR](https://github.com/ACL4SSR/ACL4SSR) 规则集合

## 配置说明

### 规则集规则

用于添加能够在 Clash 中即时生效的规则，Clash Rule Provider 会根据每条规则的**出站**生成相应的**规则集合** `📂<-` + `出站`。

### 置顶规则

这是Clash配置文件的`rules`字段中最顶部的规则，相比于其它规则它们拥有更高的优先级。Clash Rule Provider 会自动在此处添加**规则集规则**内的**规则集合**。

### 代理组

代理组中配置项的说明请参考 [Mihomo docs](https://wiki.metacubex.one/config/proxy-groups/)，
这里以两个例子说明如何定制代理组:

- 访问北邮人的代理组

北邮人拒绝国内以及所有IPv4连接，可以添加一个 `type` 为 `url-test` 的代理组，在 `url` 中填写北邮人的地址，打开 `include-all-proxies`，其余配置项保持默认。

然后，在**置顶规则**中添加一条规则: `DOMAIN,xxx.pt,PtProxy` 。

![](https://images2.imgbox.com/c9/37/FhBGLNQw_o.jpg)


- 访问ChatGPT的代理组

在**高级选项**中启用按大洲分组节点。选择Asia以外的代理组，设置`url`: `https://chatgpt.com/` , `expected-status`: `200` 。

![](https://images2.imgbox.com/e2/37/EoITSfRi_o.jpg)

### Hosts

如果需要自动更新此处使用的 Cloudflare IP, 可以通过其它[插件](https://github.com/wumode/MoviePilot-Addons)实现。