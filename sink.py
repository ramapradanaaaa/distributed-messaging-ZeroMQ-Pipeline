import sys
import time
import datetime
import zmq
import json
from encryption import AES256
import env
from DatabaseConnection import DatabaseConnection
from systemlog import SystemLog
from inbox import Inbox
from outbox import Outbox


class Sink:
    data = None

    def __init__(self):
        self.key = env.SECRET_KEY
        self.iv = env.IV_KEY
        self.context = zmq.Context()
        self.receiver = self.context.socket(zmq.PULL)
        self.receiver.bind(env.SINK_ADDR)
        self.syslog = SystemLog()
        self.db = DatabaseConnection(
            env.DB_HOST, env.DB_UNAME, env.DB_PASSWORD, env.DB_NAME)
        self.inbox = Inbox(self.db)
        self.outbox = Outbox(self.db)

    def recv_json(self):
        msg = self.receiver.recv_json()
        enc = AES256()
        plain = json.loads(enc.decrypt(self.iv, msg['data'], self.key))
        msg['data'] = plain[0]
        self.data = msg
        return msg

    def auth(self):
        if(int(self.data['sender_id']) != int(self.data['data']['sender_id'])):
            return False
        return True


sink = Sink()
while True:
    s = sink.recv_json()
    print(s)
    # authenticate message
    # if(not sink.auth()):
    #     continue
    sink.db.connect()
    # check msg apakah pesan tersebut sudah pernah masuk
    # atau tidak
    accepted = False
    checkMsgQuery = """
        select ifnull(count(*), 0) as total from tb_sync_inbox where msg_id = {} and client_unique_id = {}
    """
    checkMsg = sink.db.executeFetchOne(autoconnect=False, sql=checkMsgQuery.format(
        s['data']['msg_id'], s['data']['client_unique_id']))
    if(checkMsg['execute_status']):
        if(checkMsg['data']['total'] <= 0):
            accepted = True
    else:
        sink.syslog.insert(
            "accepted-msg", "Execute Error: {}".format(checkMsg['error_data']['msg']))

    # insert message to db
    if(accepted):
        insert = sink.inbox.insert(s['data'])
        # sql = """
        #     insert into tb_sync_inbox(row_id, table_name, msg_id, `query`, `msg_type`, client_unique_id, master_status, occur_at, first_time_occur_at)
        #     values({}, "{}", {},"{}", "{}", {}, {}, {}, {})
        # """

        # insert = sink.db.executeCommit(autoconnect=False, sql=sql.format(
        #     s['data']['row_id'], s['data']['table_name'], s['data']['msg_id'], s['data']['data'], s['data']['msg_type'], s['data']['sender_id'], s['data']['master_status'], s['data']['unix_timestamp']))
        print(insert)

        # send back which message is received using worker
        # only reply non-ACK msg
        if(s['data']['msg_type'] != 'ACK'):
            data = s['data']
            sink.outbox.insert(data={
                'row_id': 0,
                'table_name': data['table_name'],
                'msg_type': 'ACK',
                'query': data['msg_id'],
                'client_unique_id': data['client_unique_id'],
                'msg_id': 0
            })

    sink.db.close()
    print("end time: {}".format(int(round(time.time() * 1000))))
