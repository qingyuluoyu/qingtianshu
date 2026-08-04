import { Link } from "react-router-dom";

export function NotFoundPage() {
  return <section><h1>页面不存在</h1><p>请从正式导航进入产品功能。</p><Link to="/today">前往今日观察</Link></section>;
}
