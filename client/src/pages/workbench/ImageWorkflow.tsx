import EmbeddedFrame from "../../components/EmbeddedFrame";

export default function ImageWorkflow() {
  return (
    <EmbeddedFrame
      title="Amazon 产品图片工作流"
      src="/imgflow/?v=1"
      fallback={
        <>
          amazon-image-workflow 前端未运行。预期监听 <code>127.0.0.1:3000</code>。
          <br />
          启动：<code>cd ~/amazon-image-workflow && docker compose up -d</code>
        </>
      }
    />
  );
}
