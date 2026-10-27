const { createApp } = Vue;

const orderLabels = {
  pending: '待配送', picked: '已取餐', handover: '已交接', in_campus: '校内运输中',
  arrived_site: '已达楼下站点', dorm_delivery: '配送中', delivered: '已到寝完成',
  cancelled: '已取消', abnormal: '异常'
};
const statusFlow = ['pending', 'picked', 'handover', 'in_campus', 'arrived_site', 'dorm_delivery', 'delivered'];

createApp({
  data() {
    return {
      current: 'dashboard',
      tabs: [
        { id: 'dashboard', name: '概览', icon: '📊' },
        { id: 'people', name: '人员管理', icon: '👥' },
        { id: 'orders', name: '订单管理', icon: '📦' },
        { id: 'tracking', name: '配送轨迹', icon: '🛤️' },
        { id: 'photos', name: '照片审核', icon: '🖼️' },
        { id: 'anomalies', name: '异常应急', icon: '🚨' },
        { id: 'dispatch', name: '统筹调度', icon: '🚚' },
        { id: 'notifications', name: '通知中心', icon: '🔔' },
        { id: 'assistant', name: 'AI 助手', icon: '🤖' },
        { id: 'profile', name: '个人中心', icon: '👤' },
      ],
      orderLabels,
      meta: {},
      stats: { total: 0, in_transit: 0, delivered: 0, abnormal: 0 },
      notifications: [],

      notificationFilter: 'all',
      orders: [],
      orderFilter: { keyword: '', status: '' },
      showCreate: false,
      locating: false,
      newOrder: { order_no: '', customer_name: '', dorm_building: '', dorm_room: '', vendor_name: '', food_items: '', source: 'manual', longitude: '', latitude: '' },

      trackOrderNo: '',
      trackLog: {},

      photoOrderId: null,
      photoBase64: '',
      photoPreview: '',
      photoResult: null,

      anomalyOrderId: null,
      anomalyType: 'not_delivered',
      anomalyReporter: '',
      anomalies: [],

      contactModal: { show: false, anomaly: null, contacts: null, kind: '', detail: '' },

      dispatch: { plan: null, tripOrders: null },

      gps: { show: false, order: null, advance: false, longitude: '', latitude: '' },


      authed: false,
      me: null,
      token: '',
      authMode: 'login',
      authForm: { name: '', phone: '', email: '', password: '', role: 'rider' },

      currentRole: '',
      roles: [
        { id: 'admin', name: '管理员', icon: '🏫', tip: '统筹调度 · 照片审核 · 异常处置', desc: '平台统筹视角：全程监控订单、照片审核、异常处置、车次与人力调度。', tabs: ['dashboard', 'people', 'orders', 'tracking', 'photos', 'anomalies', 'dispatch', 'notifications', 'assistant', 'profile'] },
        { id: 'rider', name: '骑手', icon: '🛵', tip: '拍照上传 · 推进配送节点', desc: '骑手端：取餐 → 校外交接 → 到寝，每到一个关键节点拍照上传并推进状态，系统自动记录轨迹。', tabs: ['orders', 'tracking', 'photos', 'anomalies', 'notifications', 'assistant', 'profile'] },
        { id: 'student', name: '学生', icon: '👨‍🎓', tip: '查轨迹 · 上报异常 · 接收反馈', desc: '学生端：查看自己的订单和配送轨迹、上报异常、接收处理反馈。', tabs: ['orders', 'tracking', 'anomalies', 'notifications', 'assistant', 'profile'] },
      ],

      profile: {
        pw: { old: '', new1: '', new2: '' },
        info: { name: '', email: '', password: '', code: '', dorm_building: '', dorm_room: '' },
        switch: { password: '' },
        del: { password: '' },
      },
      forgot: { show: false, email: '', code: '', role: 'student', password: '' },

      people: {
        list: [],
        keyword: '',
        detail: null,
        orders: [],
        resetRole: '',
        resetPwd: '',
        rechargeAmount: '',
        rechargeDesc: '',
      },
      balance: { transactions: [] },

      chat: { input: '', loading: false },
      // 每个角色一条独立会话：切换角色时互不干扰
      chats: {
        admin: { thread_id: '', messages: [] },
        rider: { thread_id: '', messages: [] },
        student: { thread_id: '', messages: [] },
      },
    };
  },

  computed: {
    currentChat() {
      return this.chats[this.currentRole] || this.chats.admin;
    },
    visibleTabs() {
      const role = this.roles.find(r => r.id === this.currentRole);
      const tabs = this.tabs.filter(t => (role ? role.tabs : []).includes(t.id));
      if (this.currentRole === 'student') {
        return tabs.map(t => t.id === 'orders' ? { ...t, name: '我的订单' } : t);
      }
      return tabs;
    },
    unreadCount() {
      return this.notifications.filter(n => !n.is_read).length;
    },
    currentRoleDesc() {
      const role = this.roles.find(r => r.id === this.currentRole);
      return role ? role.desc : '';
    },
    signupRoles() {
      return this.roles.filter(r => r.id !== 'admin');
    },
  },

  mounted() {
    this.loadAll();
    setInterval(() => this.refreshNotifications(), 5000);
    setInterval(() => { if (this.current === 'dispatch' && this.dispatch.plan) this.refreshRiders(); }, 10000);
  },

  methods: {
    roleName(id) {
      const r = this.roles.find(r => r.id === id);
      return r ? r.name : id;
    },

    switchTab(id) {
      this.current = id;
      if (id === 'orders') this.loadOrders();
      if (id === 'anomalies') this.loadAnomalies();
      if (id === 'notifications') this.refreshNotifications();
      if (id === 'photos') this.loadOrders();
      if (id === 'dispatch') this.drawMapSoon();
      if (id === 'profile') { this.initProfile(); this.loadTransactions(); }
      if (id === 'people') this.loadPeople();
    },

    ensureThreadId() {
      const c = this.currentChat;
      if (!c.thread_id) {
        const uid = this.me && this.me.id ? this.me.id : 0;
        c.thread_id = `${uid}_${this.currentRole}`;
      }
      return c.thread_id;
    },

    newChat() {
      const c = this.currentChat;
      const uid = this.me && this.me.id ? this.me.id : 0;
      c.thread_id = `${uid}_${this.currentRole}_${Date.now()}`;
      c.messages = [];
      this.chat.input = '';
    },

    async sendChat() {
      const text = this.chat.input.trim();
      if (!text || this.chat.loading) return;
      const c = this.currentChat;
      const threadId = this.ensureThreadId();
      c.messages.push({ role: 'user', content: text });
      this.chat.input = '';
      this.chat.loading = true;
      this.scrollChat();
      try {
        const r = await this.api('POST', '/api/assistant/chat', { message: text, thread_id: threadId });
        const reply = r && r.reply ? r.reply : (r && r.detail ? r.detail : '助手暂时无法响应，请稍后再试。');
        if (r && r.thread_id) c.thread_id = r.thread_id;
        c.messages.push({ role: 'assistant', content: reply });
      } catch (e) {
        c.messages.push({ role: 'assistant', content: '网络异常，请稍后再试。' });
      }
      this.chat.loading = false;
      this.scrollChat();
    },

    scrollChat() {
      this.$nextTick(() => {
        const el = this.$refs.chatMessages;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },

    async submitLogin() {
      const phone = this.authForm.phone.trim();
      if (!phone) { alert('请输入手机号'); return; }
      if (!/^\d{11}$/.test(phone)) { alert('手机号必须为 11 位数字'); return; }
      if (!this.authForm.password) { alert('请输入密码'); return; }
      const user = await this.api('POST', '/api/auth/login', {
        phone: phone,
        password: this.authForm.password,
      });
      this._enter(user);
    },

    async submitRegister() {
      const name = this.authForm.name.trim();
      const phone = this.authForm.phone.trim();
      const email = this.authForm.email.trim();
      if (!name || !phone || !email) {
        alert('姓名、手机号、邮箱均需填写'); return;
      }
      if (!/^\d{11}$/.test(phone)) { alert('手机号必须为 11 位数字'); return; }
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { alert('邮箱格式不正确'); return; }
      if (!/^[A-Za-z0-9]{6,12}$/.test(this.authForm.password)) {
        alert('密码需为 6-12 位，且只能包含大小写字母和数字');
        return;
      }
      const user = await this.api('POST', '/api/auth/register', {
        name: name,
        phone: phone,
        email: email,
        password: this.authForm.password,
        role: this.authForm.role,
      });
      this._enter(user);
    },

    _enter(user) {
      if (!user || !user.id) { alert(user && user.detail ? user.detail : '操作失败'); return; }
      this.me = user;
      this.token = user.token || this.token || '';
      this.authed = true;
      this.currentRole = user.role;
      const role = this.roles.find(r => r.id === user.role);
      if (role && role.tabs.length) this.switchTab(role.tabs[0]);
    },

    logout() {
      this.authed = false;
      this.me = null;
      this.token = '';
      this.currentRole = '';
      this.authForm = { name: '', phone: '', email: '', password: '', role: 'rider' };
      this.authMode = 'login';
      // 退出登录时清空各角色会话，避免下一位登录者看到上一位的对话
      this.chats = {
        admin: { thread_id: '', messages: [] },
        rider: { thread_id: '', messages: [] },
        student: { thread_id: '', messages: [] },
      };
      this.chat.input = '';
    },

    initProfile() {
      if (this.me) {
        this.profile.info.name = this.me.name;
        this.profile.info.email = this.me.email || '';
        this.profile.info.dorm_building = this.me.dorm_building || '';
        this.profile.info.dorm_room = this.me.dorm_room || '';
      }
    },

    async changePassword() {
      const p = this.profile.pw;
      if (!p.old || !p.new1) { alert('请填写旧密码和新密码'); return; }
      if (p.new1 !== p.new2) { alert('两次输入的新密码不一致'); return; }
      if (!/^[A-Za-z0-9]{6,12}$/.test(p.new1)) { alert('新密码需为 6-12 位，且只能包含大小写字母和数字'); return; }
      const r = await this.api('POST', '/api/auth/change-password', {
        phone: this.me.phone, role: this.me.role, old_password: p.old, new_password: p.new1,
      });
      if (r && r.detail) { alert(r.detail); return; }
      alert('密码修改成功');
      this.profile.pw = { old: '', new1: '', new2: '' };
    },

    async sendProfileCode() {
      const email = this.profile.info.email.trim();
      if (!email) { alert('请先填写新邮箱'); return; }
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { alert('邮箱格式不正确'); return; }
      const r = await this.api('POST', '/api/auth/send-code', { email });
      if (r && r.detail) { alert(r.detail); return; }
      alert('验证码已发送，请查收邮箱');
    },

    async saveProfile() {
      const info = this.profile.info;
      if (!info.password) { alert('请输入当前密码'); return; }
      const emailChanged = info.email.trim() !== (this.me.email || '');
      if (emailChanged && !info.code) { alert('修改邮箱需填写邮箱验证码'); return; }
      const r = await this.api('POST', '/api/auth/update-profile', {
        phone: this.me.phone, role: this.me.role, password: info.password,
        name: info.name, email: info.email.trim(), email_code: info.code,
        dorm_building: info.dorm_building, dorm_room: info.dorm_room,
      });
      if (r && r.detail) { alert(r.detail); return; }
      this.me = r;
      this.token = r.token || this.token;
      alert('信息已更新');
      this.profile.info = { name: this.me.name, email: this.me.email || '', password: '', code: '' };
    },

    async switchRoleByPwd() {
      const pwd = this.profile.switch.password;
      if (!pwd) { alert('请输入要切换到的角色的密码'); return; }
      const user = await this.api('POST', '/api/auth/login', { phone: this.me.phone, password: pwd });
      if (!user || !user.id) { alert(user && user.detail ? user.detail : '切换失败'); return; }
      if (user.role === this.me.role) { alert('该密码对应的是当前角色'); this.profile.switch.password = ''; return; }
      this._enter(user);
      this.profile.switch.password = '';
    },

    openForgot() {
      this.forgot = { show: true, email: '', code: '', role: 'student', password: '' };
    },

    closeForgot() { this.forgot.show = false; },

    async sendForgotCode() {
      const email = this.forgot.email.trim();
      if (!email) { alert('请填写邮箱'); return; }
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { alert('邮箱格式不正确'); return; }
      const r = await this.api('POST', '/api/auth/send-code', { email });
      if (r && r.detail) { alert(r.detail); return; }
      alert('验证码已发送，请查收邮箱');
    },

    async submitResetPassword() {
      const f = this.forgot;
      const email = f.email.trim();
      if (!email) { alert('请填写邮箱'); return; }
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { alert('邮箱格式不正确'); return; }
      if (!/^[A-Za-z0-9]{6,12}$/.test(f.password)) { alert('新密码需为 6-12 位，且只能包含大小写字母和数字'); return; }
      const r = await this.api('POST', '/api/auth/reset-password', {
        email: email, code: f.code, role: f.role, new_password: f.password,
      });
      if (r && r.detail) { alert(r.detail); return; }
      alert('密码已重置，请用新密码登录');
      this.closeForgot();
    },

    async loadPeople() {
      this.people.list = await this.api('GET', '/api/admin/users');
    },

    filteredPeople() {
      const k = (this.people.keyword || '').trim();
      if (!k) return this.people.list;
      return this.people.list.filter(u =>
        (u.name || '').includes(k) || (u.phone || '').includes(k) || (u.email || '').includes(k)
      );
    },

    async openUserDetail(u) {
      const detail = await this.api('GET', '/api/admin/users/' + u.id);
      if (detail && detail.detail) { alert(detail.detail); return; }
      this.people.detail = detail;
      this.people.orders = await this.api('GET', '/api/admin/users/' + u.id + '/orders');
      this.people.resetRole = '';
      this.people.resetPwd = '';
    },

    closeUserDetail() {
      this.people.detail = null;
      this.people.orders = [];
    },

    async adminResetPassword() {
      const d = this.people.detail;
      if (!d) return;
      if (!this.people.resetRole) { alert('请选择要重置的角色'); return; }
      if (!/^[A-Za-z0-9]{6,12}$/.test(this.people.resetPwd)) { alert('新密码需为 6-12 位，且只能包含大小写字母和数字'); return; }
      const r = await this.api('POST', '/api/admin/users/' + d.id + '/reset-password', {
        role: this.people.resetRole, new_password: this.people.resetPwd,
      });
      if (r && r.detail) { alert(r.detail); return; }
      alert('密码已重置');
      this.people.resetRole = '';
      this.people.resetPwd = '';
    },

    async removeUserRole(role) {
      const d = this.people.detail;
      if (!d) return;
      if (!confirm('确定解绑该用户的「' + this.roleName(role) + '」身份？')) return;
      const r = await this.api('DELETE', '/api/admin/users/' + d.id + '/credentials/' + role);
      if (r && r.detail) { alert(r.detail); return; }
      await this.openUserDetail(d);
      this.loadPeople();
    },

    async deleteUser(u) {
      if (!confirm('确定注销用户「' + u.name + '」（' + u.phone + '）？该操作将删除其所有身份和关联，不可恢复。')) return;
      const r = await this.api('DELETE', '/api/admin/users/' + u.id);
      if (r && r.detail) { alert(r.detail); return; }
      this.closeUserDetail();
      this.loadPeople();
    },

    async deleteAccount() {
      const pwd = this.profile.del.password;
      if (!pwd) { alert('请输入当前身份的密码以确认注销'); return; }
      if (!confirm('确定注销你的账号？所有身份和关联数据将被删除，不可恢复。')) return;
      const r = await this.api('DELETE', '/api/auth/account', { password: pwd });
      if (r && r.detail) { alert(r.detail); return; }
      alert('账号已注销');
      this.logout();
    },

    viewUserOrderTrack(orderNo) {
      this.closeUserDetail();
      this.trackOrderNo = orderNo;
      this.current = 'tracking';
      this.loadTrajectory();
    },

    async loadAll() {
      await Promise.all([this.loadMeta(), this.loadStats(), this.loadOrders(), this.refreshNotifications(), this.loadAnomalies()]);
    },

    async api(method, url, body) {
      const opt = { method, headers: {} };
      if (this.token) opt.headers['X-Auth-Token'] = this.token;
      if (body) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
      let r;
      try {
        r = await fetch(url, opt);
      } catch (e) {
        return { detail: '网络请求失败，请确认服务正在运行' };
      }
      const text = await r.text();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
      if (r.ok) return data;
      let detail = (data && data.detail) ? data.detail : null;
      if (!detail) {
        const snippet = (text || '').replace(/\s+/g, ' ').trim().slice(0, 200);
        detail = snippet
          ? `服务异常（HTTP ${r.status}）：${snippet}`
          : `请求失败（HTTP ${r.status} ${r.statusText}）`;
      }
      return { detail: detail, status: r.status };
    },

    getLocation() {
      return new Promise((resolve) => {
        if (!navigator.geolocation || !navigator.geolocation.getCurrentPosition) { resolve(null); return; }
        let done = false;
        const finish = (v) => { if (!done) { done = true; resolve(v); } };
        const timer = setTimeout(() => finish(null), 10000);
        try {
          navigator.geolocation.getCurrentPosition(
            (pos) => { clearTimeout(timer); finish({ longitude: pos.coords.longitude, latitude: pos.coords.latitude }); },
            () => { clearTimeout(timer); finish(null); },
            { enableHighAccuracy: false, timeout: 6000, maximumAge: 30000 }
          );
        } catch (e) {
          clearTimeout(timer);
          finish(null);
        }
      });
    },

    async loadMeta() { this.meta = await this.api('GET', '/api/meta'); },

    async loadStats() {
      const orders = await this.api('GET', '/api/orders');
      const transitions = ['handover', 'in_campus', 'arrived_site', 'dorm_delivery'];
      this.stats = {
        total: orders.length,
        in_transit: orders.filter(o => transitions.includes(o.status)).length,
        delivered: orders.filter(o => o.status === 'delivered').length,
        abnormal: orders.filter(o => o.status === 'abnormal').length,
      };
    },

    async loadOrders() {
      const q = new URLSearchParams();
      if (this.orderFilter.status) q.set('status', this.orderFilter.status);
      if (this.orderFilter.keyword) q.set('keyword', this.orderFilter.keyword);
      this.orders = await this.api('GET', '/api/orders?' + q.toString());
      this.loadStats();
    },

    async refreshNotifications() {
      this.notifications = await this.api('GET', '/api/notifications/history?limit=50');
    },

    filteredNotifications() {
      if (this.notificationFilter === 'unread') {
        return this.notifications.filter(n => !n.is_read);
      }
      return this.notifications;
    },

    async markNotificationRead(n) {
      if (n.is_read) return;
      n.is_read = true;
      await this.api('POST', '/api/notifications/' + n.id + '/read');
    },

    async markAllRead() {
      await this.api('POST', '/api/notifications/read-all');
      this.notifications.forEach(n => { n.is_read = true; });
    },

    async deleteNotification(n) {
      if (!confirm('确定删除该通知？')) return;
      await this.api('DELETE', '/api/notifications/' + n.id);
      this.notifications = this.notifications.filter(x => x.id !== n.id);
    },

    openCreate() {
      this.showCreate = true;
      this.tryAutoLocate();
    },

    async tryAutoLocate() {
      if (this.locating) return;
      this.locating = true;
      const loc = await this.getLocation();
      this.locating = false;
      if (!this.showCreate) return;
      if (loc) {
        this.newOrder.longitude = Number(loc.longitude).toFixed(6);
        this.newOrder.latitude = Number(loc.latitude).toFixed(6);
      } else if (!String(this.newOrder.longitude || '').trim() && !String(this.newOrder.latitude || '').trim()) {
        alert('自动定位不可用（HTTP 环境限制），请手动填写经纬度；不填也可以直接保存');
      }
    },

    async createOrder() {
      const payload = { ...this.newOrder };
      const rawLng = String(this.newOrder.longitude || '').trim();
      const rawLat = String(this.newOrder.latitude || '').trim();
      if (rawLng || rawLat) {
        const lng = parseFloat(rawLng);
        const lat = parseFloat(rawLat);
        if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
          alert('经纬度格式不正确，请填写数字（如 103.88 / 30.78），或清空后直接保存');
          return;
        }
        payload.longitude = lng;
        payload.latitude = lat;
      } else {
        delete payload.longitude;
        delete payload.latitude;
      }
      try {
        const res = await this.api('POST', '/api/orders', payload);
        if (res && res.detail) { alert(res.detail); return; }
      } catch (e) {
        alert('保存失败：' + (e && e.message ? e.message : '网络或服务异常'));
        return;
      }
      this.showCreate = false;
      this.newOrder = { order_no: '', customer_name: '', dorm_building: '', dorm_room: '', vendor_name: '', food_items: '', source: 'manual', longitude: '', latitude: '' };
      this.loadOrders();
    },

    async demoBatch() {
      const buildings = ['梅园1栋', '梅园2栋', '竹园1栋', '兰园1栋', '松园1栋', '兰园2栋', '梅园3栋', '竹园2栋'];
      const names = ['张三', '李四', '王五', '赵六', '孙七', '周八', '吴九', '郑十'];
      const vendors = ['老王炒饭', '小李拉面', '阿黄麻辣烫', '张记汉堡', '食堂简餐', '奶茶小站'];
      const orders = buildings.map((b, i) => ({
        order_no: 'FW20260929' + String(i + 1).padStart(2, '0'),
        customer_name: names[i % names.length],
        dorm_building: b,
        dorm_room: String(501 + i),
        vendor_name: vendors[i % vendors.length],
        food_items: '示例餐品 #' + (i + 1),
        source: 'ocr',
      }));
      await this.api('POST', '/api/orders/batch', { orders });
      this.loadOrders();
    },

    async advanceOrder(o) {
      this.openGps(o, true);
    },

    reportLocation(o) {
      this.openGps(o, false);
    },

    openGps(o, advance) {
      this.gps.order = o;
      this.gps.advance = advance;
      this.gps.longitude = (o.longitude != null) ? o.longitude : '';
      this.gps.latitude = (o.latitude != null) ? o.latitude : '';
      this.gps.show = true;
      this.$nextTick(() => this.initGpsMap());
    },

    initGpsMap() {
      const el = document.getElementById('gps-map');
      if (!el) return;
      if (typeof AMap === 'undefined') {
        el.innerHTML = '<div style="padding:40px;text-align:center;color:#64748b;">地图 SDK 未加载，请手动输入经纬度</div>';
        return;
      }

      const hasLoc = (this.gps.longitude !== '' && this.gps.latitude !== '');
      const center = hasLoc ? [parseFloat(this.gps.longitude), parseFloat(this.gps.latitude)] : [103.881499, 30.787709];
      if (this._gpsMap) { this._gpsMap.destroy(); this._gpsMap = null; this._gpsMarker = null; }
      this._gpsMap = new AMap.Map('gps-map', { zoom: 17, center });
      if (hasLoc) this._gpsMarker = new AMap.Marker({ position: center, map: this._gpsMap });
      this._gpsMap.on('click', (e) => {
        const lng = e.lnglat.getLng();
        const lat = e.lnglat.getLat();
        this.gps.longitude = lng.toFixed(6);
        this.gps.latitude = lat.toFixed(6);
        if (this._gpsMarker) this._gpsMarker.remove();
        this._gpsMarker = new AMap.Marker({ position: [lng, lat], map: this._gpsMap });
      });
    },

    async gpsUseBrowser() {
      const loc = await this.getLocation();
      if (loc) {
        this.gps.longitude = loc.longitude;
        this.gps.latitude = loc.latitude;
        if (this._gpsMap) {
          this._gpsMap.setCenter([loc.longitude, loc.latitude]);
          if (this._gpsMarker) this._gpsMarker.remove();
          this._gpsMarker = new AMap.Marker({ position: [loc.longitude, loc.latitude], map: this._gpsMap });
        }
      } else {
        alert('自动定位失败（HTTP 环境限制），请点击地图落点或手动输入经纬度');
      }
    },

    gpsCancel() {
      this.gps.show = false;
      if (this._gpsMap) { this._gpsMap.destroy(); this._gpsMap = null; this._gpsMarker = null; }
    },

    async gpsConfirm() {
      const lng = parseFloat(this.gps.longitude);
      const lat = parseFloat(this.gps.latitude);
      if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
        alert('请点击地图落点或输入有效经纬度');
        return;
      }
      const o = this.gps.order;
      const body = { courier_name: this.me ? this.me.name : '', longitude: lng, latitude: lat };
      if (this.gps.advance) {
        const idx = statusFlow.indexOf(o.status);
        if (idx < 0 || idx >= statusFlow.length - 1) { this.gpsCancel(); return; }
        body.status = statusFlow[idx + 1];
      } else {
        body.status = o.status;
        body.location_only = true;
      }
      await this.api('PATCH', `/api/orders/${o.id}/status`, body);
      this.gpsCancel();
      this.loadOrders();
    },

    viewOrder(o) {
      this.trackOrderNo = o.order_no;
      this.current = 'tracking';
      this.loadTrajectory();
    },

    async loadTrajectory() {
      if (!this.trackOrderNo) return;
      this.trackLog = await this.api('GET', '/api/tracking/log/' + encodeURIComponent(this.trackOrderNo));
    },

    onFilePick(e) {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        this.photoBase64 = reader.result.split(',')[1] || '';
        this.photoPreview = reader.result;
      };
      reader.readAsDataURL(file);
    },

    genDemo(type) {
      const c = document.createElement('canvas');
      c.width = 320; c.height = 240;
      const ctx = c.getContext('2d');
      if (type === 'black') {
        ctx.fillStyle = '#000'; ctx.fillRect(0, 0, 320, 240);
      } else if (type === 'noise') {
        const img = ctx.createImageData(320, 240);
        for (let i = 0; i < img.data.length; i += 4) {
          img.data[i] = Math.random() * 255; img.data[i + 1] = Math.random() * 255;
          img.data[i + 2] = Math.random() * 255; img.data[i + 3] = 255;
        }
        ctx.putImageData(img, 0, 0);
      } else if (type === 'blurry') {
        ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 320, 240);
        ctx.filter = 'blur(14px)';
        ctx.fillStyle = '#888'; ctx.fillRect(60, 80, 200, 80);
        ctx.filter = 'none';
      } else {
        ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 320, 240);
        ctx.fillStyle = '#dff'; ctx.fillRect(0, 0, 320, 80);
        ctx.fillStyle = '#000'; ctx.font = 'bold 26px sans-serif';
        ctx.fillText('外卖单号 FW2026092901', 20, 120);
        ctx.fillStyle = '#464'; ctx.fillRect(20, 150, 120, 40);
        ctx.fillStyle = '#fff'; ctx.font = '20px sans-serif';
        ctx.fillText('寝室 512', 30, 178);
      }
      this.photoPreview = c.toDataURL('image/png');
      this.photoBase64 = c.toDataURL('image/png').split(',')[1];
    },

    async uploadPhoto() {
      if (!this.photoOrderId || !this.photoBase64) { alert('请选择订单并上传/生成图片'); return; }
      const order = this.orders.find(o => o.id === this.photoOrderId);
      this.photoResult = await this.api('POST', '/api/photos/upload', {
        order_id: this.photoOrderId,
        file_base64: this.photoBase64,
        file_ext: 'png',
        expected_order_no: order ? order.order_no : '',
        expected_room: order ? order.dorm_room : '',
      });
    },

    async loadAnomalies() {
      this.anomalies = await this.api('GET', '/api/anomalies');
    },

    async reportAnomaly() {
      if (!this.anomalyOrderId) { alert('请选择订单'); return; }
      await this.api('POST', '/api/anomalies', {
        order_id: this.anomalyOrderId,
        anomaly_type: this.anomalyType,
        reported_by: this.anomalyReporter || (this.me ? this.me.name : '用餐人'),
        description: this.anomalyType === 'lost' ? '外卖丢失' : '未配送到寝',
      });
      this.loadAnomalies();
    },

    async checkTimeouts() {
      const r = await this.api('POST', '/api/anomalies/check-timeouts');
      alert('触发补偿异常数：' + r.triggered.length);
      this.loadAnomalies();
    },

    async locateAnomaly(a) { await this.api('POST', `/api/anomalies/${a.id}/locate`); this.loadAnomalies(); },
    async handleAnomaly(a) { await this.api('POST', `/api/anomalies/${a.id}/handle`, { action: '核实中', operator: '站点负责人', detail: '正在核对交接与站点记录' }); this.loadAnomalies(); },

    async openContact(a, kind) {
      const contacts = await this.api('GET', `/api/anomalies/${a.id}/contacts`);
      if (contacts && contacts.detail) { alert(contacts.detail); return; }
      const target = kind === 'rider' ? contacts.rider : contacts.student;
      if (!target) { alert(kind === 'rider' ? '该订单暂无关联骑手' : '该订单暂无关联学生（需在个人中心填寝室号）'); return; }
      this.contactModal = {
        show: true, anomaly: a, contacts, kind, target,
        detail: kind === 'rider' ? '订单异常，请核实该环节配送情况' : '异常已处理，请查收',
      };
    },

    closeContactModal() {
      this.contactModal = { show: false, anomaly: null, contacts: null, kind: '', target: null, detail: '' };
    },

    async confirmContact() {
      const m = this.contactModal;
      if (!m.anomaly) return;
      const action = m.kind === 'rider' ? '联系骑手' : '反馈学生';
      await this.api('POST', `/api/anomalies/${m.anomaly.id}/handle`, { action, operator: this.me ? this.me.name : '管理员', detail: m.detail });
      this.closeContactModal();
      this.loadAnomalies();
    },

    async compensateAnomaly(a) { await this.api('POST', `/api/anomalies/${a.id}/compensate`); this.loadAnomalies(); },
    async resolveAnomaly(a) { await this.api('POST', `/api/anomalies/${a.id}/resolve?resolution=已核实并退款完成`); this.loadAnomalies(); },

    async viewAnomalyTrajectory(a) {
      const order = this.orders.find(o => o.id === a.order_id);
      this.trackOrderNo = order ? order.order_no : a.order_id;
      this.current = 'tracking';
      this.loadTrajectory();
    },

    async planDispatch() {
      this.dispatch.plan = await this.api('POST', '/api/dispatch/plan');
      this.$nextTick(() => this.drawMap());
    },

    viewTripOrders(t) {
      this.dispatch.tripOrders = t;
    },

    drawMapSoon() { if (this.dispatch.plan) this.$nextTick(() => this.drawMap()); },

    drawMap() {
      if (!this.dispatch.plan) return;
      const el = document.getElementById('map');
      if (!el) return;
      if (typeof AMap === 'undefined') {
        el.innerHTML = '<div style="padding:40px;text-align:center;color:#64748b;">地图 SDK 未加载，请先在 index.html 填入高德 JS API Key 与安全密钥</div>';
        return;
      }
      if (this._amap && this._amap.getContainer && this._amap.getContainer() !== el) {
        this._amap.destroy();
        this._amap = null;
        this._riderMarkers = [];
      }
      if (!this._amap) this._amap = new AMap.Map('map', { zoom: 16 });
      const map = this._amap;
      map.clearMap();

      const colors = ['#e11d48', '#0ea5e9', '#f59e0b', '#10b981', '#8b5cf6', '#ec4899'];
      const keyPoints = [];
      this.dispatch.plan.trips.forEach((t, i) => {
        const col = colors[i % colors.length];
        const path = t.route.map(p => [p.lon, p.lat]);
        if (path.length > 1) {
          new AMap.Polyline({ path, strokeColor: col, strokeWeight: 4, strokeOpacity: 0.9, map });
        }
        t.route.forEach(p => { if (p.point) keyPoints.push({ lon: p.lon, lat: p.lat, label: p.point, col }); });
      });

      const seen = new Set();
      keyPoints.forEach(k => {
        if (seen.has(k.label)) return;
        seen.add(k.label);
        new AMap.Marker({
          position: [k.lon, k.lat],
          map,
          content: '<div style="background:' + k.col + ';color:#fff;font-size:11px;padding:2px 6px;border-radius:3px;white-space:nowrap;">' + k.label + '</div>',
        });
      });

      this.drawRiders(map);
      map.setFitView();
    },

    drawRiders(map) {
      if (this._riderMarkers) this._riderMarkers.forEach(m => m.remove());
      this._riderMarkers = [];
      const transitions = ['handover', 'in_campus', 'arrived_site', 'dorm_delivery'];
      this.orders.forEach(o => {
        if (!transitions.includes(o.status)) return;
        if (o.longitude == null || o.latitude == null) return;
        this._riderMarkers.push(new AMap.Marker({
          position: [o.longitude, o.latitude],
          map,
          content: '<div style="width:12px;height:12px;background:#f59e0b;border:2px solid #fff;border-radius:50%;box-shadow:0 0 4px rgba(0,0,0,.4);"></div>',
        }));
      });
    },

    async refreshRiders() {
      if (!this._amap) return;
      await this.loadOrders();
      this.drawRiders(this._amap);
    },

    async loadTransactions() {
      this.balance.transactions = await this.api('GET', '/api/balance/transactions?limit=50');
    },

    async adminRecharge() {
      const d = this.people.detail;
      if (!d) return;
      const amt = parseFloat(this.people.rechargeAmount);
      if (!amt || amt <= 0) { alert('请输入大于 0 的充值金额'); return; }
      const r = await this.api('POST', '/api/balance/recharge', {
        user_id: d.id, amount: amt, description: this.people.rechargeDesc || '',
      });
      if (r && r.detail) { alert(r.detail); return; }
      alert('充值成功');
      this.people.rechargeAmount = '';
      this.people.rechargeDesc = '';
      await this.openUserDetail(d);
      this.loadPeople();
    },

  }
}).mount('#app');