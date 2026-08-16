---
trigger: always_on
---
# 项目研发规范

> **适用范围**：本规范适用于所有前后端项目的代码开发，所有开发人员必须严格遵守。
> 规范分为两个执行级别：标注"**必须**"、"**禁止**"的条目为**强制执行**，标注"**优先**"、"**推荐**"的条目为最佳实践。

---

## 一、UI/UX 设计规范

1. 所有界面设计必须遵守 `ui-ux-pro-max` 规范，采用现代化风格，禁止使用过时设计元素。
2. **后台管理页面**：优先使用网格布局、卡片式布局、筛选器、排序器等复杂交互组件，禁止仅做简单列表和表格。
3. **前台/用户端页面**：符合用户使用习惯，页面功能丰富、视觉高端，避免页面过于简陋。
4. 所有页面交互设计必须符合完整的业务逻辑，避免出现逻辑错误或前后不一致。
5. 功能模块设计必须结合真实业务场景，实现完整业务闭环；一个完整项目数据库表**不得少于 15 张**（最低要求）。
6. 前端所有表格列必须**居中展示**。
7. 所有枚举值展示必须展示其对应的**描述文本**，优先从数据字典获取，禁止前端硬编码枚举文案。
8. 列表中如有 ID 字段关联名称，必须展示关联名称；查询条件中涉及关联 ID 的，必须改为**下拉选择框**，禁止让用户直接输入 ID。

> **📋 开发前强制自查清单（第8条执行检查点，每次开发列表/筛选页面前必过）**
>
> | 检查项                       | 检查方式                                 | 未通过处理                                 |
> | ---------------------------- | ---------------------------------------- | ------------------------------------------ |
> | 列表是否有 `xxxId` 字段？    | 逐列扫描 VO 字段                         | 后端 VO 补 `xxxName`，五步范式批量关联查询 |
> | 枚举字段是否直接显示原始值？ | 检查 `status`、`type`、`strategy` 等字段 | 加 `<a-tag>` 转中文标签                    |
> | 查询条件是否有 ID 类筛选项？ | 扫描 `query` 对象字段                    | 改为 `a-select`，`onMounted` 加载选项数据  |
> | 多级筛选是否实现联动清空？   | 如「应用→API」                           | 上级变化时清空下级并重新加载               |

---

## 一一、数据单一来源规范（强制，违反即不合格产出）

> **核心原则：任何业务数据只能有一个权威来源，所有展示层必须从该来源读取，禁止一切形式的硬编码复制。**

1. **禁止前端硬编码业务数据**：所有来自后台配置的数值、文案、规则（如积分数值、枚举描述、费率、限制次数等），**必须通过接口动态获取**，禁止在前端 Vue/JS 文件中写死。
   - 违规示范：`<em>+10 分</em>`、`每日上限 8 次`（直接写死后台可配置的值）
   - 正确做法：调用对应配置接口（如 `enabledRules`），用 `rule.awardPoints`、`rule.dailyLimit` 动态渲染

2. **数据只从一个地方出（Single Source of Truth）**：
   - 后端配置表（如 `t_points_rule`、`t_sys_dict`、`t_config`）是数据的唯一权威来源
   - 前端展示、后端业务逻辑、接口响应，三者均必须从同一数据源读取，禁止任何一层私自维护数据副本
   - 配置变更只需改数据库，所有展示**自动生效**；**禁止改了数据库还需要同步改代码**

3. **禁止前端复刻后端枚举/配置**：
   - 禁止在前端定义与后端枚举或配置表对应的静态 Map/常量对象，应通过接口或数据字典获取
   - 如需本地缓存，必须在运行时从接口加载后缓存，禁止编译期写死

4. **必须从数据源动态读取的场景（以下一律禁止硬编码）**：
   - 积分规则（积分数值、每日上限、规则名称、是否需要审核）
   - 枚举描述文本（订单状态、业务类型、操作类型等）
   - 费率、折扣、价格区间上下限
   - 菜单权限路径
   - 任何运营可在后台动态配置的参数

---

## 二、后端开发规范

### 2.1 代码风格规范

1. 避免不必要的对象复制或克隆。
2. 避免多层嵌套，优先使用**提前返回（Early Return）**减少缩进层级。
3. 涉及共享资源必须使用适当的并发控制机制（分布式锁、原子类等）。
4. **注释规范（强制）**：
   - 所有业务代码必须写注释，**禁止使用行尾注释**。
   - 类和方法使用 Javadoc 文档注释，作者统一填写 `qingfeng`。
   - 方法体内每行代码上方使用单行注释，清楚说明该行的业务逻辑；逻辑复杂处使用多行注释。
5. **代码间距规范（强制）**：方法之间、不同逻辑块之间必须保留空行隔开，禁止代码拥挤不分层。
6. **大括号规范（强制）**：所有控制语句（`if`、`else`、`for`、`while`、`do` 等）的执行体**必须使用大括号 `{}`**，即使只有一行代码也禁止省略。

### 2.2 Java 编码规范（严格执行）

1. **流式编程优先**：所有集合操作优先使用 Stream + Lambda 链式调用，禁止使用显式 `for` 循环处理集合。
2. **Builder 构建对象**：实体类统一加 `@Builder` 注解，非必要**禁止 `new + setter` 模式**；写代码前先确认目标类是否有 `@Builder`，没有则补上。
3. **构造器注入**：Spring Bean 依赖注入必须使用**构造器注入**，禁止在字段上直接使用 `@Autowired` 注入。
4. **Hutool 工具类优先**：对象判空、字符串处理、集合操作等优先使用 `hutool` 工具包，减少手写 `if (obj == null)` 判断。
5. **Optional 替代 null 检查**：使用 `Optional.ofNullable().orElseThrow()` 等链式调用，根据 JDK 版本动态选择合适的 API。
6. **积极使用当前项目 JDK 版本对应的新特性**：**强制要求**根据项目所用 JDK 版本合理运用新特性简化开发，必须充分利用项目所用 JDK 版本已支持的新 API，代码更简洁高级，禁止用旧式写法替代已有新 API。以下为 JDK 9~11+ 常用特性（JDK 17/21 项目可额外使用 Record、Sealed Class、Pattern Matching 等），按项目实际 JDK 版本取用：
   - **集合工厂方法**：`List.of()`、`Set.of()`、`Map.of()`、`Map.entry()` 替代 new + add
   - **Optional 增强**：`Optional.or()`、`Optional.ifPresentOrElse()`、`Optional.stream()`
   - **Stream 增强**：`Stream.ofNullable()`、`Stream.takeWhile()`、`Stream.dropWhile()`、`Stream.iterate()`
   - **String 增强**：`String.isBlank()`、`String.strip()`、`String.lines()`、`String.repeat()`
   - **var 关键字**：局部变量类型推断，减少冗长的类型声明（如 `var map = new HashMap<String, List<Integer>>()`）
   - **Files 工具**：`Files.readString()`、`Files.writeString()` 替代繁琐的流操作
   - **HTTP Client**：`java.net.http.HttpClient` 替代第三方库进行简单 HTTP 请求
7. **Lambda 内计数使用 AtomicInteger**：Lambda 闭包内修改外部变量必须使用 `AtomicInteger`，禁止在 Lambda 内修改普通 `int` 变量。
8. **MyBatis-Plus Lambda 条件写法**：条件查询优先使用 Lambda 流式调用，条件判断内联写在链式调用中，如 `.eq(condition, Entity::getField, value)`。
9. **禁止内联包名**：所有引用的类必须在文件顶部使用 `import` 导入，**禁止将包名内联写在代码中**（如 `new com.example.Foo()` 这种写法属于违规）。

### 2.3 接口设计规范

1. 所有业务接口按 `module` 模块划分，每个模块下建立独立的 `controller` 包，模块间功能独立、互不耦合。
2. **开发顺序**：先搭建后端接口并定义好响应规范 → 再开发前端，前后端数据结构必须严格保持一致。
3. 所有查询接口禁止连表查询，必须拆分为**单表批量查询 + 内存组装**的模式。

### 2.4 性能规范（强制执行，不可违反）

> 以下规范违反一处视为**严重性能缺陷**，必须立即重构。

- **禁止 N+1 查询**：禁止在 Stream 或循环内部调用任何单条数据库查询（`selectById`、`selectOne`、含单个固定值的 `selectList` 等）。
- **列表接口五步范式（必须遵循）**：
  1. 执行主查询（分页/全量），获取主记录列表；
  2. 用 `Stream + Collectors.toSet()` 提取所有关联外键 ID 并去重；
  3. 对每类外键 ID 执行一次批量查询（`selectBatchIds` 或 `IN` 条件），每种关联数据只查一次；
  4. 用 `Collectors.toMap(Entity::getId, e -> e)` 构建内存索引 Map；
  5. 组装阶段所有关联数据从内存 Map 取值（`map.get` / `map.getOrDefault`），禁止在此阶段触发任何额外查询。
- **禁止 N 次 COUNT**：统计关联数量时，一次性查出全部关联记录，用 `Collectors.groupingBy + Collectors.counting()` 内存统计，禁止逐条主记录执行 COUNT。
- **详情接口子列表批量化**：所有子列表 ID 一次性收集后批量查询，禁止逐条主记录循环触发子查询。
- **同语义数据只查一次**：同一请求内相同语义的数据集合只查一次，结果赋变量后复用；语义不同（如全局视角 vs 个人视角）必须分别查询，禁止强行复用导致业务逻辑错误。
- **OR 条件必须合并**：对同一张表执行多个 OR 条件查询时，必须合并为一次带 `or()` 的查询，禁止拆分为多次查询后合并结果。
- **仅查必要字段**：查询目的仅为收集 ID 时，必须使用 `.select(Entity::getId)` 限制返回字段，禁止 `SELECT *` 后只取 ID。
- **慢 SQL 监控强制接入**：所有后端服务必须配置 MyBatis Interceptor 慢 SQL 拦截器，阈值 500ms，超阈值输出 WARN 日志并携带 Mapper 方法全名。

### 2.5 参数校验规范（Bean Validation，强制执行）

- **声明式优先**：优先使用 Bean Validation 注解校验，禁止在 Service 层用 `if` 手动校验可声明化的格式/空值规则。

- **Controller 必须开启校验**：所有 `@RequestBody` / `@RequestParam` 参数必须加 `@Validated` 或 `@Valid`，禁止遗漏。

- **常用注解速查**：

  | 注解                      | 适用场景                                     |
  | ------------------------- | -------------------------------------------- |
  | `@NotNull`                | 对象/包装类型不为 null                       |
  | `@NotBlank`               | 字符串不为空串或纯空白（字符串字段优先用此） |
  | `@NotEmpty`               | 集合/数组/字符串不为空                       |
  | `@Size(min, max)`         | 字符串长度或集合大小范围                     |
  | `@Min` / `@Max`           | 数值最小/最大值                              |
  | `@Range(min, max)`        | 数值范围（Hibernate Validator 扩展）         |
  | `@Pattern(regexp)`        | 手机号、邮编等正则校验                       |
  | `@Email`                  | 邮箱格式                                     |
  | `@Future` / `@Past`       | 时间方向约束                                 |
  | `@Positive` / `@Negative` | 数值正负约束                                 |

- **嵌套对象级联校验**：DTO 中嵌套对象字段必须加 `@Valid` 触发级联校验，禁止只校验外层对象。

- **分组校验**：新增与更新复用同一 DTO 时，使用 `@Validated(Create.class)` / `@Validated(Update.class)` 分组，禁止同一套规则导致校验冲突。

- **自定义校验注解**：无法用标准注解表达的业务规则（枚举合法性、编码唯一性等），必须封装为自定义 `@Constraint` 注解，禁止在 Service 层散落大量 if 判断。

- **统一异常处理**：`MethodArgumentNotValidException`（@RequestBody 场景）和 `ConstraintViolationException`（@RequestParam 场景）必须在 `GlobalExceptionHandler` 中统一捕获，以标准 `ResponseDTO` 格式返回，禁止原始异常暴露给前端。

- **message 必须中文可读**：所有校验注解 message 必须为中文业务描述（如"手机号不能为空"），禁止使用框架默认英文提示。

- **Service 层不重复校验**：格式/空值校验不在 Service 层重复执行；业务状态校验（记录是否存在、状态流转合法性等）仍需在 Service 层通过抛出 `BizException` 防护，两层职责明确分离。

### 2.6 分层架构规范（四层架构，强制执行）

> 本项目后端采用 **Controller → Service → Manager → Dao** 四层架构，每层职责严格划分，禁止跨层调用。

#### 各层职责定义

| 层次           | 包名          | 核心职责                                                     | 禁止事项                                                     |
| -------------- | ------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| **Controller** | `controller/` | 接收 HTTP 请求、参数校验、权限注解、调用 Service、返回 `ResponseDTO` | 禁止写任何业务逻辑；禁止直接调用 Dao 或 Manager              |
| **Service**    | `service/`    | 核心业务逻辑编排：事务控制、业务规则判断、跨 Manager 数据组装、状态流转 | 禁止直接操作 Dao（通过 Manager 间接访问）；禁止写与业务无关的通用查询逻辑 |
| **Manager**    | `manager/`    | 通用数据访问封装：**必须继承 `ServiceImpl<XxxDao, XxxEntity>`**，仅对接 Dao，封装复用性高的单表/多表查询、批量操作，供多个 Service 复用 | 禁止写业务判断逻辑（if 业务状态等）；禁止调用其他模块的 Service；禁止直接在 Service 中调 Dao 绕过 Manager |
| **Dao**        | `dao/`        | 数据库操作接口（MyBatis Plus `BaseMapper` 扩展），仅做数据存取 | 禁止写业务逻辑；复杂 SQL 使用 Mapper XML，禁止在 Java 代码里拼接 SQL |

#### 调用链规则（强制）

```
Controller  →  Service  →  Manager  →  Dao
    ↑               ↑
 仅做路由        核心逻辑
```

- **禁止跨层调用**：Controller 不得直接调 Manager 或 Dao；Service 不得直接调 Dao（必须经过 Manager）。
- **Manager 必须继承 `ServiceImpl`**：Manager 类必须继承 `ServiceImpl<XxxDao, XxxEntity>`，使其天然具备单表增删改查、`saveBatch`、`listByIds` 等 MyBatis-Plus 通用能力，无需重复实现。
- **Manager 可被多个 Service 复用**：通用查询、批量查询、条件构造等封装在 Manager 中，避免重复代码散落各 Service。
- **Service 之间可以互调**：同模块内或跨模块的 Service 互调是允许的，但需注意事务边界和循环依赖。
- **Dao 仅由 Manager 持有**：除 Manager 外，其他层不得注入 Dao 实例。

#### 命名规范

- Manager 类命名：`{业务名}Manager`，例如 `OrderManager`、`UserManager`
- Manager 文件位置：`module/{模块名}/manager/` 包下
- Manager 方法命名：以数据视角命名，如 `getByOrderId`、`batchGetByIds`、`listByUserId`，禁止用业务语义命名（如 `checkUserCanRefund` 属于业务逻辑，应在 Service 中）

#### 典型分层示例

```java
// ✅ 正确：Manager 继承 ServiceImpl，Service 调 Manager，Manager 调 Dao

// OrderManager.java
@Service
public class OrderManager extends ServiceImpl<OrderDao, OrderEntity> {

    private final OrderDao orderDao;

    public OrderManager(OrderDao orderDao) {
        this.orderDao = orderDao;
    }

    /**
     * 按支付订单号查询订单
     *
     * @param payOrderId 支付订单号
     * @return 订单实体
     * @author qingfeng
     */
    public OrderEntity getByPayOrderId(String payOrderId) {
        // 按主键查询订单
        return orderDao.selectById(payOrderId);
    }
}

// OrderService.java - 调 Manager，专注业务逻辑
public OrderVO queryDetail(String payOrderId) {
    // 通过 Manager 获取订单实体
    OrderEntity order = orderManager.getByPayOrderId(payOrderId);
    // 通过 Manager 批量查商品项
    List<OrderItemEntity> items = orderItemManager.listByPayOrderId(payOrderId);
    // 业务逻辑：组装 VO
    return buildOrderVO(order, items);
}

// ❌ 错误：Service 直接调 Dao
public OrderVO queryDetail(String payOrderId) {
    // 违规！应通过 Manager 访问
    OrderEntity order = orderDao.selectById(payOrderId);
}
```

#### 存量代码兼容说明

> 项目中存在部分早期代码直接在 Service 中调用 Dao（历史遗留），**新增代码必须严格遵循四层规范**；涉及重构时，优先补充 Manager 层并迁移 Dao 调用。

---

### 2.7 接口返回类型规范：VO vs Entity 按需选择

> **原则：按需选择，不强制用 VO，但需要关联名称时必须用 VO。**

| 场景                                    | 推荐返回类型                        | 说明                                                   |
| --------------------------------------- | ----------------------------------- | ------------------------------------------------------ |
| 简单单表 CRUD，无关联数据需要展示       | Entity 直接返回                     | 简单、无凗余，可接受                                   |
| 需要展示关联名称（如 appName、apiName） | VO 继承 Entity，追加 `xxxName` 字段 | **必须用 VO**，禁止返回裸 Entity                       |
| 分页列表接口含外键 ID                   | VO，预先规划所有 `xxxName` 字段     | 设计 VO 时一次性把所有 Name 字段加齐，避免后续反复改造 |
| 详情接口含子列表                        | VO 包含子列表字段                   | 子列表同样适用五步范式                                 |

**VO 设计范式（关联名称场景）：**

```java
// ✅ 正确：VO 继承 Entity，追加名称字段
@Data
@EqualsAndHashCode(callSuper = true)
public class XxxVO extends XxxEntity {
    /** 关联应用名称（批量查询 oap_app 组装）*/
    private String appName;
    /** 关联 API 名称（批量查询 oap_api_info 组装）*/
    private String apiName;
}

// ❌ 错误：直接返回 Entity，前端只能看到数字 ID
public ResponseDTO<PageResult<OapXxxEntity>> list(...) { ... }
```

---

### 2.8 前端响应式绑定与筛选联动规范

**规则一：禁止将 `v-model` 直接绑定到 `computed` 返回的对象属性上**

`computed` 每次计算返回新的普通对象，Vue 无法追踪其属性修改，导致开关/输入框操作无效。

```vue
<!-- ❌ 错误：computed 返回的临时对象属性，v-model 绑定无效 -->
<a-switch v-model:checked="computedList[i].someField" />

<!-- ✅ 正确：维护独立的响应式 Map，通过 :checked + @change 驱动 -->
<a-switch
  :checked="stateMap[record.id]?.someField ?? false"
  @change="(val) => handleChange(record.id, val)"
/>
```

**规则二：多级筛选必须实现联动清空（强制）**

当筛选条件存在级联关系（如「应用 → API」、「分组 → 接口」），必须：

1. 上级变更时，**自动清空下级已选值**（`query.xxxId = null`）
2. 上级变更时，**重新加载下级选项数据**
3. 上级未选时，下级必须**禁用**并显示提示文字

```vue
<a-select v-model:value="query.appId" @change="onAppChange" />
<a-select
  v-model:value="query.apiId"
  :placeholder="query.appId ? '请选择API' : '请先选择应用'"
  :disabled="!query.appId"
/>

// onAppChange 必须执行两步
const onAppChange = (appId) => {
  query.apiId = null          // 清空下级
  loadApiOptions(appId)       // 重新加载下级选项
}
```

---

## 三、数据库设计规范

### 3.1 表结构基础规范

1. **三个基础字段必须齐全**，所有业务表不得缺少：

   ```sql
   `id`          int UNSIGNED  NOT NULL AUTO_INCREMENT                           COMMENT '主键ID',
   `create_time` datetime      NOT NULL DEFAULT CURRENT_TIMESTAMP                COMMENT '创建时间',
   `update_time` datetime      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
   ```

   > 主键可使用自增 `int UNSIGNED` 或雪花算法 `bigint`，禁止使用字符串类型主键。

2. **日期类型统一使用 `datetime`**：禁止使用 `timestamp`（存在 2038 年问题及时区问题）、`date`（丢失时分秒）、`int` 存时间戳等替代方案。

3. **代码层日期类型统一使用 `LocalDateTime`**：Java 实体类中所有日期字段必须使用 `java.time.LocalDateTime`，禁止使用 `java.util.Date`、`java.sql.Timestamp` 等旧式类型。MyBatis Plus 已内置自动类型转换，无需额外配置。

4. **日期字段必须加格式化注解（强制）**：所有 `LocalDateTime` 字段必须同时加以下两个注解，禁止少加任何一个：

   ```java
   @DateTimeFormat(pattern = "yyyy-MM-dd HH:mm:ss")
   @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8")
   private LocalDateTime createTime;
   ```

   > `@DateTimeFormat` 控制入参解析（请求入口）；`@JsonFormat` 控制响应序列化格式（返回数据），缺少任一个均会导致日期显示异常。

### 3.2 命名规范

- **表名**：`模块前缀_业务名`，全小写 snake_case，例如 `sys_user`、`biz_order`、`app_config`。
- **字段名**：全小写 snake_case，禁止使用驼峰命名或大写字母。
- **布尔字段**：使用 `is_` 前缀 + `tinyint(1)` 类型，0 = 否，1 = 是，例如 `is_enable`、`is_delete`。

### 3.3 其他规范

- **字段注释必须填写**：所有字段必须添加 `COMMENT`，清晰描述字段含义和取值范围；枚举字段须在注释中列举所有枚举值及含义，例如：`COMMENT '状态: 0-禁用, 1-启用'`。
- **逻辑删除优先**：业务核心数据使用逻辑删除（`is_delete` 字段标记），禁止直接物理删除，保证数据可追溯与可恢复。

---

## 四、SQL 变更管理规范

### 4.1 目录结构规范

所有数据库变更文件统一放在 `db/` 目录下，按分支类型分为 `main/` 和 `feature/` 两个子目录。

**核心设计原则：每个分支（包括 main 和每个 feature 需求分支）都有自己独立的 `test.sql` + `prod.sql` 完整快照，快照在目录顶层，`changelog/` 在其下存放该分支每次具体的增量变更。上线时，直接执行对应分支下的 `prod.sql` 即可，无需逐条执行 changelog。**

完整目录结构如下：

```
db/
├── main/
│   ├── test.sql                               ← 主干全量快照（含所有已合并的历史变更，从零部署用）
│   ├── prod.sql                               ← 主干全量快照（上线时直接执行一次）
│   └── changelog/                             ← 主干历史增量变更记录（细粒度，调试/追溯用）
│       ├── 20260626/
│       │   └── 01_init_all_tables.sql
│       ├── 20260630/
│       │   ├── 01_member_user_auth.sql
│       │   └── 02_remove_oap_member.sql
│       └── 20260701/
│           ├── 01_add_origin_crowd_new_apis.sql
│           └── 02_add_origin_crowd_api_params.sql
└── feature/
    └── {feature-branch-name}/                 ← 分支名与 Git 分支对应（去掉 "feature/" 前缀）
        ├── test.sql                           ← 本需求分支完整快照（含本分支所有变更，测试环境用）
        ├── prod.sql                           ← 本需求分支完整快照（上线时直接执行此文件）
        └── changelog/                         ← 本需求分支增量变更细节（开发过程逐步执行用）
            └── 20260701/
                ├── 01_add_xxx.sql
                └── 02_update_xxx.sql
```

**路径速查表（AI 助手创建文件时必须对照此表，禁止凭经验估猜路径）：**

| 文件类型                              | 完整路径                                                     |
| ------------------------------------- | ------------------------------------------------------------ |
| 主干测试快照                          | `db/main/test.sql`                                           |
| 主干生产快照                          | `db/main/prod.sql`                                           |
| 主干增量变更（在 main 分支时）        | `db/main/changelog/{YYYYMMDD}/{NN_变更简述}.sql`             |
| 需求分支测试快照                      | `db/feature/{分支名}/test.sql`                               |
| 需求分支生产快照                      | `db/feature/{分支名}/prod.sql`                               |
| 需求分支增量变更（在 feature 分支时） | `db/feature/{分支名}/changelog/{YYYYMMDD}/{NN_变更简述}.sql` |

---

### 4.2 各部分职责说明

| 文件/目录        | 完整路径                                          | 定位                           | 使用时机                     |
| ---------------- | ------------------------------------------------- | ------------------------------ | ---------------------------- |
| 主干测试快照     | `db/main/test.sql`                                | 含所有已合并需求的主干全量快照 | 主干测试环境从零部署时执行   |
| 主干生产快照     | `db/main/prod.sql`                                | 同上，生产环境版本             | 主干上线时执行一次           |
| 主干增量变更     | `db/main/changelog/{日期}/{序号}.sql`             | 主干历史增量记录               | 在已有主干测试库上调试追溯   |
| 需求分支测试快照 | `db/feature/{分支名}/test.sql`                    | 本需求所有变更的完整累积快照   | 本需求测试环境从零部署时执行 |
| 需求分支生产快照 | `db/feature/{分支名}/prod.sql`                    | 本需求所有变更的完整累积快照   | **上线时直接执行此文件**     |
| 需求分支增量变更 | `db/feature/{分支名}/changelog/{日期}/{序号}.sql` | 本需求每次具体的细粒度变更     | 开发过程中在已有库上逐步执行 |

**快照文件同步要求（强制）**：每次往 `changelog/` 新增变更文件时，**必须同步更新本分支下的 `test.sql` 和 `prod.sql`**，保证快照始终是本分支所有变更的最新全量状态。

---

### 4.3 changelog 记录规范

- **文件夹命名**：`YYYYMMDD`（如 `20260608`），每个工作日一个文件夹
- **文件命名**：`NN_变更简述.sql`，序号从 `01` 开始，代表当天第 N 次变更
- **每个文件头部必须注释**：

```sql
-- [变更说明] 修复积分菜单 url_path 权限路径错误
-- [变更时间] 2026-06-08
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/main/test.sql] 是
-- [同步至 db/main/prod.sql] 是
```

---

### 4.4 AI 助手创建 SQL 文件的分支判断规则（强制）

> **AI 助手每次新建 SQL 变更文件前，必须先判断当前 Git 分支，确定存放路径，禁止凭经验直接创建文件。**

```
创建 SQL 变更文件前必须执行的判断流程：

  第一步：执行 git branch --show-current 获取当前分支名

  第二步：根据分支名选择路径
    ├── 若当前在 main 分支
    │   → changelog 路径：db/main/changelog/{今日日期}/{NN_变更简述}.sql
    │   → 快照文件：db/main/test.sql 和 db/main/prod.sql
    │
    └── 若当前在 feature 分支（如 feature/core_origin_crowd_skill_20260630）
        → 取分支名去掉 "feature/" 前缀，得到 {分支名}
        → changelog 路径：db/feature/{分支名}/changelog/{今日日期}/{NN_变更简述}.sql
        → 快照文件：db/feature/{分支名}/test.sql 和 db/feature/{分支名}/prod.sql

  第三步：创建目录（不存在时）并写入 changelog 文件

  第四步：同步更新本分支目录下的 test.sql 和 prod.sql
```

**禁止行为（违反即为不合格产出）：**

- 禁止在 feature 分支开发时，将 SQL 变更写入 `db/main/changelog/`
- 禁止将快照文件 test.sql/prod.sql 放到 `db/` 根目录
- 禁止 feature 分支的快照同步到 `db/main/`（main 的快照只在分支合并后才更新）
- 禁止未确认分支直接创建文件

---

### 4.5 使用流程

```
有新 SQL 变更时：
  1. 执行 git branch --show-current 确认当前分支
  2. 按 4.4 分支判断规则确定文件存放路径
  3. 在对应 changelog/ 目录下建当天日期文件夹（已存在则直接用）
  4. 建序号文件 01_xxx.sql、02_xxx.sql…
  5. 将变更 SQL 写入对应文件（头部加注释，含变更说明、时间、变更人）
  6. 将该变更同步写入并更新本分支下的 test.sql
  7. 将该变更同步写入并更新本分支下的 prod.sql
  8. 在测试库执行当天最新的 changelog 文件

知道要执行什么：
  → 看对应分支的 changelog/ 目录，找最新日期文件夹，里面按序号依次执行

本需求分支上线：
  → 直接执行 db/feature/{分支名}/prod.sql 全文，无需关注 changelog

main 主干上线：
  → 直接执行 db/main/prod.sql 全文即可

feature 分支合并后：
  → 将 db/feature/{分支名}/changelog/ 下的变更文件复制到 db/main/changelog/ 对应日期目录
  → 将本分支的快照内容并入更新 db/main/test.sql 和 db/main/prod.sql
```

---

### 4.6 幂等性设计规范（强制）

所有 SQL 变更必须设计为**可重复执行不报错**：

| 操作类型 | 幂等写法                                                     |
| -------- | ------------------------------------------------------------ |
| 建表     | `CREATE TABLE IF NOT EXISTS`                                 |
| 加字段   | 先判断字段是否存在，或捕获 `1060 Duplicate column` 错误      |
| 插入数据 | `INSERT IGNORE INTO` 或 `INSERT ... ON DUPLICATE KEY UPDATE` |
| 菜单插入 | 执行前先 `DELETE FROM t_menu WHERE menu_id = xxx`，再 INSERT |
| 更新数据 | `UPDATE ... WHERE` 条件本身具有幂等性                        |

---

### 4.7 上线规范

1. **正式环境只执行 `db/main/prod.sql`**：prod.sql 是完整快照，上线时执行一次即可，不需要执行 changelog
2. **禁止破坏性语句**：`db/main/prod.sql` 中禁止出现无条件的 `DROP TABLE`、`TRUNCATE`；如确需删除，必须加 `IF EXISTS` 并在注释中说明原因
3. **合并前检查**：分支合并（PR）前确认 `db/main/test.sql` 和 `db/main/prod.sql` 均已包含本次所有变更，禁止代码已合并但 SQL 遗漏

---

## 五、测试规范

1. **数据结构一致性验证**：优先检查前后端数据字段、数据结构、数据类型是否严格一致，发现不一致必须修复后再提测。
2. **功能完整性验证**：测试每个模块的功能是否完善、可用，业务逻辑是否符合产品设计意图。
3. **接口规范验证**：验证接口是否正常响应、返回数据格式是否符合接口响应规范（`ResponseDTO` 标准包装）。

---

## 六、项目目录结构规范

> **适用范围**：所有后端服务、前端项目必须严格遵守以下目录结构规范，新增模块禁止随意建包。

---

### 6.1 后端项目结构（Spring Boot）

```
{root-package}                      # 根包，如 com.example、net.smart.sphere
├── module/                     # 业务模块目录，按领域划分
│   └── {module}/               # 模块名，如 order、goods、user
│       ├── controller/         # 路由控制层
│       │   ├── web/            # 后台管理接口（/web/** 路由前缀）
│       │   └── front/          # 前台用户接口（/front/** 路由前缀）
│       ├── service/            # 核心业务逻辑层
│       ├── manager/            # 通用数据访问层（必须继承 ServiceImpl）
│       ├── dao/                # 数据库操作层（继承 BaseMapper）
│       └── job/                # 定时任务（可选，有定时任务时才建包）
├── domain/                     # 领域模型，按业务模块划分
│   └── {module}/               # 模块名，与 module/ 目录一一对应
│       ├── entity/             # 数据库实体类（映射数据库表）
│       ├── vo/                 # 视图对象（返回给前端）
│       ├── form/               # 表单对象（接收前端入参）
│       ├── dto/                # 数据传输对象（服务间传输）
│       └── enums/              # 模块相关枚举类
└── config/                     # 全局配置类（非模块级配置放此）
```

> **多 Maven 模块项目说明**：如果项目拆分了多个 Maven 模块（如本项目的 `smart-base` + `smart-biz`），可将 `domain/` 放入基础模块、`module/` 放入业务模块，但**包结构内部层次不变**。包名根据各项目实际定义，没有固定要求。

> **命名要求**：
>
> - Entity：`{Model}Entity`，如 `OrderEntity`
> - VO：`{Model}VO`，如 `OrderVO`，列表和详情共用同一个 VO
> - Form：`{Model}QueryForm`（分页查询）、`{Model}AddForm`（新建）、`{Model}UpdateForm`（编辑）
> - Enum：`{Model}{Field}Enum`，如 `OrderStateEnum`
> - Controller：`{Model}Controller`，如 `OrderController`
> - Service：`{Model}Service`，如 `OrderService`
> - Manager：`{Model}Manager`，如 `OrderManager`
> - Dao：`{Model}Dao`，如 `OrderDao`

---

### 6.2 前端管理后台（SmartAdminWeb - Vue3 + Ant Design Vue）

```
src/
├── api/                        # 接口封装层，按功能域划分
│   ├── business/               # 业务模块接口
│   │   └── {module}/           # 如 order/、goods/、partner/
│   ├── support/                # 支撑功能接口（文件、消息、数据字典等）
│   └── system/                 # 系统管理接口（用户、角色、菜单等）
├── views/                      # 页面视图，与 api/ 目录对应
│   ├── business/
│   │   └── {module}/           # 模块页面，如 order/order-list.vue
│   ├── support/
│   └── system/
├── components/                 # 全局共用组件
│   ├── framework/              # 框架级组件（如 SmartTable、SmartDialog）
│   ├── business/               # 业务共用组件
│   ├── support/                # 支撑功能组件
│   └── system/                 # 系统模块组件
├── constants/                  # 常量定义
│   ├── business/               # 业务模块枚举/常量
│   ├── support/                # 支撑模块枚举/常量
│   ├── system/                 # 系统模块枚举/常量
│   ├── common-const.js         # 全局通用常量（分页大小等）
│   └── index.js                # 常量统一导出
├── router/                     # 路由配置
│   ├── index.js                # 主路由（登录、布局等）
│   ├── routers.js              # 所有路由集合
│   ├── support/                # 支撑功能路由
│   └── system/                 # 系统管理路由
├── store/                      # Pinia/Vuex 状态管理
├── layout/                     # 布局组件（顶栅布局、侧边栏布局等）
├── lib/                        # axios 封装、通用工具方法
├── config/                     # 前端全局配置（接口地址等）
├── style/                      # 全局样式
├── theme/                      # 主题配置
├── i18n/                       # 国际化
├── directives/                 # 自定义指令（如权限指令 v-permission）
├── utils/                      # 工具函数
├── App.vue                     # 根组件
└── main.js                     # 入口文件
```

---

### 6.3 前端用户端（SmartPC - Vue3 前台）

```
src/
├── api/                        # 接口封装，按业务划分
│   └── {module}/               # 如 order/、course/、points/
├── views/                      # 页面视图，与 api/ 目录对应
│   └── {module}/               # 如 orders/、details/、my-account/
├── components/                 # 全局共用组件
├── constants/                  # 常量定义
├── router/                     # 路由配置，按业务模块建子包
├── store/                      # 状态管理
├── layout/                     # 布局组件
├── lib/                        # axios 封装、工具方法
├── config/                     # 前端全局配置
├── style/                      # 全局样式
├── theme/                      # 主题配置
├── i18n/                       # 国际化
├── directives/                 # 自定义指令
├── useHooks/                   # 自定义 Composition API Hooks
├── utils/                      # 工具函数
├── App.vue
└── main.js
```

---

### 6.4 目录命名规范

#### 后端（Java）

| 目录类型   | 命名规范              | 示例                                      |
| ---------- | --------------------- | ----------------------------------------- |
| 模块包     | 全小写单词            | `order`、`goods`、`partner`               |
| Entity类   | `{Model}Entity`       | `OrderEntity`                             |
| VO 类      | `{Model}VO`           | `OrderVO`、`OrderRefundVO`                |
| Form 类    | `{Model}{Action}Form` | `OrderQueryForm`、`OrderRefundCreateForm` |
| Controller | `{Model}Controller`   | `OrderController`                         |
| Service    | `{Model}Service`      | `OrderService`                            |
| Manager    | `{Model}Manager`      | `OrderManager`                            |
| Dao        | `{Model}Dao`          | `OrderDao`                                |
| Enum       | `{Model}{Field}Enum`  | `OrderStateEnum`                          |

#### 前端（Vue）

| 目录/文件类型 | 命名规范                             | 示例                                 |
| ------------- | ------------------------------------ | ------------------------------------ |
| 模块目录      | 全小写 kebab-case                    | `order/`、`goods/`                   |
| 页面文件      | `{module}-{action}.vue`              | `order-list.vue`、`order-refund.vue` |
| API 文件      | `{module}-api.js`                    | `order-api.js`、`goods-api.js`       |
| 常量文件      | `{module}.js` 或 `{module}-const.js` | `order.js`、`common-const.js`        |
| 路由文件      | `{module}.js`                        | `order.js`                           |

---

### 6.5 层应对关系

各层必须严格对齐，禁止层乎不匹配：

```
前层          后层
——————      ————————————
前端 Vue       →   Controller
                   ↓
              Service
                   ↓
              Manager
                   ↓
               Dao 
                   ↓
     Entity/VO/Form (domain)
```

- **api/ 层**：每个模块对应一个 `xxx-api.js`，与后端 `Controller` 一一对应
- **views/ 层**：页面文件必须放入对应业务模块目录，禁止直接放在 views/ 根目录
- **constants/ 层**：前端枚举常量必须放入 constants/ 对应目录，禁止内嵌在页面文件中硬编码

---

## 七、AI 助手 / Agent 协作规范（强制执行）

> **适用范围**：本项目依赖 Qoder Agent / Claude Code 等 AI 助手参与开发，在调用 AI 助手完成任务时，必须保证其遵循以下准则。

### 7.1 Skill 优先使用原则（强制）

AI 助手在接到任何技术任务时，必须优先调用环境中已安装的专业 Skill，不得在已有匹配 Skill 的情况下仅凭直觉产出代码或方案。

#### 7.1.1 两个强制调用节点

| 阶段                                 | 规则                                                         |
| ------------------------------------ | ------------------------------------------------------------ |
| **出方案 / 分析 / 对比 / 评估 阶段** | 接到 "如何设计"、"选哪个"、"对比 X 与 Y"、"推荐方案"、"架构设计" 类问题时，**必须先调用对应 Skill 拿到专业框架**，再基于框架输出方案。禁止凭经验直接给出方案。 |
| **实施 / 编码 / 修改 阶段**          | 开工前必须扫描环境可用 Skill 列表，匹配后立即调用，按 Skill 的设计原则动手。 |

#### 7.1.2 技术栈对应 Skill 清单（必须调用）

> 按任务类型查表，找到匹配行后**必须调用对应 Skill 再动手**，禁止跳过。多类型任务可叠加多个 Skill。

---

**▌调研 & 分析类**

| 任务类型                    | 优先调用的 Skill                                             |
| --------------------------- | ------------------------------------------------------------ |
| 代码库结构摸底 / 依赖梳理   | `codebase-onboarding`、`repo-scan`、`code-tour`              |
| 陌生仓库快速上手 / 环境检查 | `workspace-surface-audit`、`automation-audit-ops`            |
| 技术调研 / 方案搜索         | `search-first`、`deep-research`、`research-ops`、`exa-search` |
| 文档查阅 / 第三方库接口参考 | `documentation-lookup`                                       |
| 竞品分析 / 市场研究         | `market-research`、`competitive-platform-analysis`、`benchmark-methodology` |
| 需求拆解 / 验收标准定义     | `intent-driven-development`、`product-lens`、`product-capability` |
| 多方案对比 / 重大技术决策   | `council`、`brainstorming`                                   |
| 复杂架构 / 多步骤实施规划   | `blueprint`、`writing-plans`                                 |

---

**▌后端开发类（按语言 / 框架）**

| 任务类型                       | 优先调用的 Skill                                             |
| ------------------------------ | ------------------------------------------------------------ |
| Spring Boot / Java 后端        | `springboot-patterns`、`java-coding-standards`、`jpa-patterns` |
| Spring Security / 认证授权     | `springboot-security`                                        |
| Quarkus / Quarkus + Camel      | `quarkus-patterns`、`quarkus-security`                       |
| Kotlin 后端 / 协程 / Ktor      | `kotlin-patterns`、`kotlin-coroutines-flows`、`kotlin-ktor-patterns` |
| Kotlin ORM（Exposed）          | `kotlin-exposed-patterns`                                    |
| Python 通用后端                | `python-patterns`                                            |
| Django / Django REST Framework | `django-patterns`、`django-security`、`django-celery`        |
| FastAPI / Pydantic v2          | `fastapi-patterns`                                           |
| Go 后端                        | `golang-patterns`                                            |
| Node.js / NestJS               | `nestjs-patterns`、`backend-patterns`                        |
| PHP / Laravel                  | `laravel-patterns`、`laravel-security`                       |
| Rust 后端                      | `rust-patterns`                                              |
| C# / .NET                      | `dotnet-patterns`                                            |
| Perl                           | `perl-patterns`、`perl-security`                             |
| Android / KMP 架构             | `android-clean-architecture`                                 |
| tinystruct Java 框架           | `tinystruct-patterns`                                        |

---

**▌数据库 & 缓存类**

| 任务类型                     | 优先调用的 Skill      |
| ---------------------------- | --------------------- |
| MySQL / MariaDB 设计与优化   | `mysql-patterns`      |
| PostgreSQL 设计与优化        | `postgres-patterns`   |
| Redis 缓存 / 分布式锁 / 限流 | `redis-patterns`      |
| ClickHouse 分析型查询        | `clickhouse-io`       |
| 数据库迁移 / 零停机变更      | `database-migrations` |
| Prisma ORM                   | `prisma-patterns`     |

---

**▌API & 集成类**

| 任务类型               | 优先调用的 Skill                     |
| ---------------------- | ------------------------------------ |
| REST API 接口设计      | `api-design`                         |
| 新增第三方 API 集成    | `api-connector-builder`              |
| MCP Server 构建        | `mcp-server-patterns`、`mcp-builder` |
| 错误处理 / 重试 / 熔断 | `error-handling`                     |
| 内容哈希缓存设计       | `content-hash-cache-pattern`         |

---

**▌前端开发类**

| 任务类型                         | 优先调用的 Skill                                             |
| -------------------------------- | ------------------------------------------------------------ |
| Vue 3 / Composition API / Pinia  | `vue-patterns`                                               |
| Nuxt 4 / SSR                     | `nuxt4-patterns`                                             |
| React 18/19 / Next.js            | `react-patterns`、`frontend-patterns`                        |
| Angular / 信号响应               | `angular-developer`                                          |
| Vite 构建配置                    | `vite-patterns`                                              |
| Next.js Turbopack                | `nextjs-turbopack`                                           |
| UI 组件样式（shadcn / Tailwind） | `ui-styling`                                                 |
| UI 设计 / 组件构建 / 样式优化    | `ui-ux-pro-max`、`frontend-design`、`make-interfaces-feel-better` |
| 动效 / 过渡动画                  | `motion-foundations`、`motion-patterns`、`motion-advanced`、`motion-ui` |
| 无障碍设计（WCAG 2.2）           | `accessibility`、`frontend-a11y`                             |
| Vue 截图转组件                   | `ui-to-vue`                                                  |

---

**▌移动端 & 跨平台类**

| 任务类型                    | 优先调用的 Skill                            |
| --------------------------- | ------------------------------------------- |
| Flutter / Dart              | `dart-flutter-patterns`                     |
| SwiftUI / iOS 开发          | `swiftui-patterns`、`swift-concurrency-6-2` |
| Swift 并发与持久化          | `swift-actor-persistence`                   |
| iOS 26 Liquid Glass 设计    | `liquid-glass-design`                       |
| Compose Multiplatform / KMP | `compose-multiplatform-patterns`            |
| Apple 设备端 LLM            | `foundation-models-on-device`               |

---

**▌测试类（按语言 / 框架）**

| 任务类型                       | 优先调用的 Skill                                      |
| ------------------------------ | ----------------------------------------------------- |
| 通用 TDD 工作流（跨语言）      | `tdd-workflow`、`test-driven-development`             |
| Spring Boot 单元/集成测试      | `springboot-tdd`、`springboot-verification`           |
| Django 测试                    | `django-tdd`、`django-verification`                   |
| Laravel 测试                   | `laravel-tdd`、`laravel-verification`                 |
| Quarkus 测试                   | `quarkus-tdd`、`quarkus-verification`                 |
| Python 测试（pytest）          | `python-testing`                                      |
| Go 测试                        | `golang-testing`                                      |
| Rust 测试                      | `rust-testing`                                        |
| React 组件测试                 | `react-testing`                                       |
| Kotlin 测试（Kotest/MockK）    | `kotlin-testing`                                      |
| C# / F# 测试                   | `csharp-testing`、`fsharp-testing`                    |
| C++ 测试（GoogleTest）         | `cpp-testing`                                         |
| Perl 测试                      | `perl-testing`                                        |
| Swift 测试（DI + 协议 Mock）   | `swift-protocol-di-testing`                           |
| Flutter/Dart 代码审查          | `flutter-dart-code-review`                            |
| E2E 浏览器自动化（Playwright） | `e2e-testing`                                         |
| Web 应用本地功能验证           | `webapp-testing`、`browser-qa`                        |
| Windows 桌面 E2E 测试          | `windows-desktop-e2e`                                 |
| AI 回归测试                    | `ai-regression-testing`                               |
| 性能基准测试                   | `benchmark`                                           |
| 完成前验证（禁止空口声称通过） | `verification-before-completion`、`verification-loop` |
| 部署后金丝雀监控               | `canary-watch`                                        |

---

**▌代码审查 & 安全类**

| 任务类型                       | 优先调用的 Skill                                  |
| ------------------------------ | ------------------------------------------------- |
| 代码审查（逻辑 Bug / SOLID）   | `code-review-expert`、`gateguard`                 |
| 安全审查（认证 / 注入 / 密钥） | `security-review`、`security-scan`                |
| Spring Boot 安全               | `springboot-security`                             |
| Django 安全                    | `django-security`                                 |
| Laravel 安全                   | `laravel-security`                                |
| Quarkus 安全                   | `quarkus-security`                                |
| 漏洞赏金级安全挖掘             | `security-bounty-hunter`                          |
| DeFi 智能合约安全              | `defi-amm-security`                               |
| 交易智能体安全                 | `llm-trading-agent-security`                      |
| 医疗 PHI 合规 / HIPAA          | `healthcare-phi-compliance`、`hipaa-compliance`   |
| 代码质量实时评分               | `codehealth-mcp`、`plankton-code-quality`         |
| 高风险改动双智能体对抗验证     | `santa-method`                                    |
| 生产就绪审计                   | `production-audit`                                |
| 智能体架构审计                 | `agent-architecture-audit`                        |
| 接收 / 请求代码审查            | `receiving-code-review`、`requesting-code-review` |

---

**▌调试 & 故障诊断类**

| 任务类型                       | 优先调用的 Skill                                             |
| ------------------------------ | ------------------------------------------------------------ |
| 任何 Bug / 测试失败 / 异常行为 | `systematic-debugging`（遇 Bug 必须先调用）                  |
| 按钮/交互类隐性状态 Bug 追踪   | `click-path-audit`                                           |
| 完整 Bug 修复流程编排          | `orch-fix-defect`                                            |
| 智能体流程失败诊断             | `agent-introspection-debugging`                              |
| 性能问题递归优化               | `benchmark-optimization-loop`                                |
| 低延迟系统诊断                 | `latency-critical-systems`                                   |
| 监控仪表板构建                 | `dashboard-builder`                                          |
| 网络接口错误 / 抖动 / 丢包     | `network-interface-health`                                   |
| BGP 路由 / 邻居状态诊断        | `network-bgp-diagnostics`                                    |
| 路由器/交换机配置上线前检查    | `network-config-validation`                                  |
| Cisco IOS 配置审查             | `cisco-ios-patterns`                                         |
| SSH 自动化采集                 | `netmiko-ssh-automation`                                     |
| 家庭/homelab 网络故障          | `homelab-network-setup`、`homelab-pihole-dns`、`homelab-wireguard-vpn` |

---

**▌工程工具 & DevOps 类**

| 任务类型                    | 优先调用的 Skill              |
| --------------------------- | ----------------------------- |
| Git 分支策略 / 提交规范     | `git-workflow`                |
| GitHub Issue / PR / CI 管理 | `github-ops`                  |
| Docker / Compose 容器化     | `docker-patterns`             |
| Kubernetes 部署与管理       | `kubernetes-patterns`         |
| CI/CD 流水线 / 部署策略     | `deployment-patterns`         |
| 可复现跨平台开发环境        | `flox-environments`           |
| Git Worktree 特性分支隔离   | `using-git-worktrees`         |
| 大数据摄取 / ETL 加速       | `data-throughput-accelerator` |
| 六边形架构 / 端口适配器     | `hexagonal-architecture`      |

---

**▌ML / AI 工程类**

| 任务类型                         | 优先调用的 Skill       |
| -------------------------------- | ---------------------- |
| 向现有项目引入 ML 能力           | `ml-adoption-playbook` |
| 生产级 ML 工程（训练/部署/监控） | `mle-workflow`         |
| PyTorch 深度学习                 | `pytorch-patterns`     |

---

#### 7.1.3 例外情况（允许不调用 Skill）

- 纯读取文件、查看目录结构、查看 git 状态等信息型查询
- 单一字段改名、拼写错误修正、一行改动
- 用户明确说 "just do it" / "直接改" / "不用调 skill"

---

#### 7.1.4 专家团智能体对应技能配置（必须对齐）

> 本项目使用 Qoder 内置专家团功能，每个专家智能体应按以下清单配置技能，确保其具备对应领域的专业能力。

**▌调研员**（调研分析 / 代码定位 / 依赖梳理 / 报告输出）

| 优先级 | 技能                        | 说明                           |
| ------ | --------------------------- | ------------------------------ |
| 核心   | `codebase-onboarding`       | 陌生代码库结构分析与入口说明   |
| 核心   | `repo-scan`                 | 全量代码资产审计，梳理依赖     |
| 核心   | `deep-research`             | 多源深度研究，输出带引用的报告 |
| 核心   | `search-first`              | 编码前优先搜索，避免重复造轮子 |
| 核心   | `research-ops`              | 基于当前证据的事实性调研工作流 |
| 推荐   | `documentation-lookup`      | 实时查阅第三方库最新文档       |
| 推荐   | `workspace-surface-audit`   | 审计项目工具与配置现状         |
| 推荐   | `code-tour`                 | 生成结构化代码导览文件         |
| 推荐   | `exa-search`                | Exa 神经搜索（Web/代码/情报）  |
| 推荐   | `intent-driven-development` | 将模糊需求转化为可验收标准     |
| 推荐   | `council`                   | 多方案结构化分析与决策         |

---

**▌全栈工程师**（前后端实现与修改 / 跨栈编码）

| 优先级 | 技能                                            | 说明                               |
| ------ | ----------------------------------------------- | ---------------------------------- |
| 核心   | `springboot-patterns`                           | Spring Boot 架构模式（本项目主栈） |
| 核心   | `java-coding-standards`                         | Java 编码规范                      |
| 核心   | `jpa-patterns`                                  | JPA/MyBatis Plus 实体与查询        |
| 核心   | `api-design`                                    | REST 接口设计规范                  |
| 核心   | `mysql-patterns`                                | MySQL 查询与索引优化               |
| 核心   | `vue-patterns`                                  | Vue 3 Composition API              |
| 核心   | `frontend-patterns`                             | React/Next.js 前端模式             |
| 核心   | `error-handling`                                | 跨语言错误处理与熔断               |
| 推荐   | `redis-patterns`                                | Redis 缓存/分布式锁                |
| 推荐   | `docker-patterns`                               | 容器化与服务编排                   |
| 推荐   | `git-workflow`                                  | 分支策略与提交规范                 |
| 推荐   | `blueprint`                                     | 多步骤实施规划                     |
| 推荐   | `database-migrations`                           | 数据库迁移最佳实践                 |
| 推荐   | `ui-styling`                                    | shadcn/ui + Tailwind 组件样式      |
| 可选   | 其他语言/框架技能（按项目实际使用的技术栈选配） | —                                  |

---

**▌QA**（测试构建 / 验证流程 / 证据收集）

| 优先级 | 技能                                                         | 说明                                     |
| ------ | ------------------------------------------------------------ | ---------------------------------------- |
| 核心   | `tdd-workflow`                                               | 跨语言 TDD，80%+ 覆盖率要求              |
| 核心   | `verification-before-completion`                             | 完成前必须运行命令验证，禁止空口声称通过 |
| 核心   | `verification-loop`                                          | 全面验证循环系统                         |
| 核心   | `springboot-tdd`                                             | JUnit5 + Mockito + Testcontainers        |
| 核心   | `springboot-verification`                                    | Spring Boot 构建→分析→测试→安全扫描      |
| 核心   | `e2e-testing`                                                | Playwright E2E 测试                      |
| 推荐   | `webapp-testing`                                             | 本地 Web 应用 Playwright 功能验证        |
| 推荐   | `browser-qa`                                                 | 视觉测试与 UI 交互自动化                 |
| 推荐   | `benchmark`                                                  | 性能基准测试与回归检测                   |
| 推荐   | `ai-regression-testing`                                      | AI 辅助开发的回归测试策略                |
| 推荐   | `canary-watch`                                               | 部署后端点与性能监控                     |
| 可选   | 框架级 TDD 技能（django-tdd / laravel-tdd / golang-testing 等，按项目栈选配） | —                                        |

---

**▌代码审查员**（代码审查 / 风险识别 / 改进建议）

| 优先级 | 技能                                                         | 说明                                    |
| ------ | ------------------------------------------------------------ | --------------------------------------- |
| 核心   | `code-review-expert`                                         | 高信号代码审查，检测逻辑 Bug/SOLID 违反 |
| 核心   | `security-review`                                            | 安全清单审查（认证/注入/密钥/API）      |
| 核心   | `gateguard`                                                  | 操作前强制调查门卫，防止草率修改        |
| 核心   | `receiving-code-review`                                      | 接收审查反馈时保持技术严谨性            |
| 核心   | `requesting-code-review`                                     | 合并前请求规范的代码审查                |
| 推荐   | `springboot-security`                                        | Spring Boot 安全最佳实践                |
| 推荐   | `codehealth-mcp`                                             | CodeScene 实时代码健康评分              |
| 推荐   | `production-audit`                                           | 生产就绪性全面审计                      |
| 推荐   | `santa-method`                                               | 双智能体对抗验证（高风险改动时使用）    |
| 推荐   | `plankton-code-quality`                                      | 编写时代码质量实时执行                  |
| 推荐   | `security-scan`                                              | Claude Code 配置安全扫描                |
| 可选   | 框架级安全技能（django-security / laravel-security 等，按项目栈选配） | —                                       |

---

**▌UI 操作者**（浏览器 & UI 端到端验证 / 可视化 Bug 复现）

| 优先级 | 技能                          | 说明                                     |
| ------ | ----------------------------- | ---------------------------------------- |
| 核心   | `e2e-testing`                 | Playwright E2E 测试（POM/CI/截图）       |
| 核心   | `browser-qa`                  | 视觉测试与 UI 交互自动化验证             |
| 核心   | `webapp-testing`              | 本地 Web 应用 Playwright 测试            |
| 核心   | `click-path-audit`            | 追踪按钮完整状态序列，发现交互类隐性 Bug |
| 核心   | `ui-demo`                     | 录制 UI 演示视频，可视化操作路径         |
| 推荐   | `canary-watch`                | 部署后 HTTP/控制台错误/性能自动巡检      |
| 推荐   | `windows-desktop-e2e`         | Windows 桌面原生应用 E2E 测试            |
| 推荐   | `accessibility`               | WCAG 2.2 AA 无障碍合规验证               |
| 推荐   | `make-interfaces-feel-better` | 检查间距/排版/交互状态是否符合设计规范   |

---

**▌故障诊断工程师**（故障复现 / 根因定位 / 缺陷诊断 / 修复建议）

| 优先级 | 技能                                                         | 说明                                    |
| ------ | ------------------------------------------------------------ | --------------------------------------- |
| 核心   | `systematic-debugging`                                       | 系统化调试工作流（遇 Bug 必须优先调用） |
| 核心   | `click-path-audit`                                           | 交互类 Bug 状态路径追踪                 |
| 核心   | `orch-fix-defect`                                            | 编排"复现→修复→验证→提交"完整流程       |
| 核心   | `error-handling`                                             | 错误处理模式，定位异常传播路径          |
| 推荐   | `agent-introspection-debugging`                              | 智能体流程自调试（捕获→诊断→隔离恢复）  |
| 推荐   | `production-audit`                                           | 生产环境准备度审计，排查上线前隐患      |
| 推荐   | `benchmark-optimization-loop`                                | 性能问题递归优化与基准对比              |
| 推荐   | `canary-watch`                                               | 部署后持续监控，快速发现回归            |
| 推荐   | `dashboard-builder`                                          | 构建回答真实运维问题的监控仪表板        |
| 可选   | `network-interface-health`、`network-bgp-diagnostics`、`cisco-ios-patterns`（基础设施层故障时选配） | —                                       |

### 7.2 Skill 调用质量要求

1. **必须基于 Skill 输出的原则动手**，不能只调用不使用；Skill 中的 anti-pattern 必须避免
2. **同一任务可多 Skill 叠加**：如后端任务同时需调 `springboot-patterns` + `jpa-patterns` + `springboot-security`
3. **调用有充分上下文**：传入具体任务描述，不能只传空参数
4. **被用户提醒"没用 skill"等于本次产出失败**，需重新带 Skill 产出

### 7.3 会话起始检查项

AI 助手在新会话 / 新任务开始时，必须检查：

- [ ] 本会话可用的 Skill 有哪些？（扫描 system-reminder）
- [ ] 本任务匹配哪个 Skill？
- [ ] 项目记忆中是否已记录用户偏好与项目约定？调 SearchMemory 核实
- [ ] 项目本规范中是否有与任务相关的强制条款？

### 7.4 违反后果

- AI 助手违反本节规范产出的代码 / 方案 为 **不合格产出**，必须重新调 Skill 后重做
- 多次违反者，应调整 AI 助手的调用习惯（写入记忆、强化提示词）