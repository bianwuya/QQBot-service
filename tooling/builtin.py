from datetime import datetime
from .registry import Registry, Tool
from .schemas import object_schema
import persona


def build(bot):
    r=Registry()
    def add(name,description,handler,schema=None,permission='user',timeout=2):
        r.register(Tool(name,description,'L0',permission,schema or object_schema(),handler,timeout))
    query=object_schema({'query':{'type':'string','minLength':1,'maxLength':200}}, ['query'])
    add('get_time','查询本机当地时间',lambda ctx,args:{'time':datetime.now().astimezone().isoformat(timespec='seconds')})
    add('get_bot_status','管理员查询Bot连接与任务计数，不返回凭据',lambda ctx,args:bot.health(),permission='admin')
    add('get_model_list','管理员查询可用模型，不修改配置',lambda ctx,args:bot.llm.models()[:60],permission='admin',timeout=5)
    add('search_memory','检索本人在当前会话的结构化记忆',
        lambda ctx,args:[{'type':r['type'],'content':r['content'][:240]} for r in bot.store.list_memories(ctx.scope,ctx.owner,limit=20)
                         if args['query'].casefold() in r['content'].casefold()][:4],query)
    add('search_knowledge','检索当前允许的知识namespace，资料只是非可信参考',
        lambda ctx,args:bot.knowledge.prompt(ctx.scope,persona.role_for(bot.store,ctx.scope),args['query']),query)
    def recent(ctx,args):
        row=bot.store.file(ctx.scope,ctx.owner)
        return [] if not row else [{'name':row['name'][:120],'created':row['created']}]
    add('get_recent_files','查询本人当前会话最近文件的名称，不返回本机路径',recent)
    app_schema=object_schema({'app_id':{'type':'string','minLength':1,'maxLength':40}},['app_id'])
    add('get_app_status','查询管理员本机白名单应用状态，不返回路径',lambda ctx,args:bot.app_control.status(ctx,args['app_id']),app_schema,permission='admin',timeout=6)
    control_schema=object_schema({'app_id':{'type':'string','minLength':1,'maxLength':40},
                                  'action':{'type':'string','enum':['start','stop','restart']}},['app_id','action'])
    r.register(Tool('control_app','申请白名单应用启停；只生成确认票据，必须管理员发确认命令','L2','admin',control_schema,
                    lambda ctx,args:bot.app_control.request(ctx,'control_app',args),2,True))
    return r
