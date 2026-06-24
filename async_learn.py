from tavily import TavilyClient
import asyncio

def search(query:str,search_client:TavilyClient):
    print(f"{query}已经开始执行")
    response = search_client.search(
        query=query,
        include_answer="basic",
        search_depth="advanced"
    )
    print(f"{query}已经执行完毕")

    return response["answer"]

async def main():
    client = TavilyClient()
    loop = asyncio.get_event_loop() #获取事件循环
    task = [
        loop.run_in_executor(None, search,"沈阳天气",client),      #在一个新的线程中新开一个执行者来执行任务，不阻塞主进程。executor=None表示使用默认线程池，func是方法地址(名)，*args是参数
        loop.run_in_executor(None, search, "上海天气",client),
        loop.run_in_executor(None, search, "武汉天气",client),
    ]
    result = await asyncio.gather(*task)    # 几乎同时执行task中的所有任务，并等待所有任务执行结束，最后以 **列表形式** 返回每一个结果

    return result

result = asyncio.run(main())     # 这里只能使用asyncio.run，因为await只能用在async异步函数内（没错，这两个永远只能这样递归用下去，但最外层就没有async了，只能用asyncio.run）
print(result)