import sys
sys.path.insert(0, 'build/shared_model/bindings')
import iroha

import block_pb2
import endpoint_pb2
import endpoint_pb2_grpc
import queries_pb2
import grpc
import time

tx_builder = iroha.ModelTransactionBuilder()
query_builder = iroha.ModelQueryBuilder()
crypto = iroha.ModelCrypto()
proto_tx_helper = iroha.ModelProtoTransaction()
proto_query_helper = iroha.ModelProtoQuery()

manager_pub = open("manager@global.pub", "r").read()
manager_priv = open("manager@global.priv", "r").read()

key_pair = crypto.convertFromExisting(manager_pub, manager_priv)

creator = "manager@global"
tx_counter = 1
query_counter = 1

def get_time():
    return int(round(time.time() * 1000)) - 10**5

def get_status(tx):
    # Create status request

    print("Hash of the transaction: ", tx.hash().hex())
    tx_hash = tx.hash().blob()

    if sys.version_info[0] == 2:
        tx_hash = ''.join(map(chr, tx_hash))
    else:
        tx_hash = bytes(tx_hash)

    request = endpoint_pb2.TxStatusRequest()
    request.tx_hash = tx_hash

    channel = grpc.insecure_channel('127.0.0.1:50051')
    stub = endpoint_pb2_grpc.CommandServiceStub(channel)

    response = stub.Status(request)
    status = endpoint_pb2.TxStatus.Name(response.tx_status)
    print("Status of transaction is:", status)

    if status != "COMMITTED":
        print("Your transaction wasn't committed")
        exit(1)


def print_status_streaming(tx):
    # Create status request

    print("Hash of the transaction: ", tx.hash().hex())
    tx_hash = tx.hash().blob()

    # Check python version
    if sys.version_info[0] == 2:
        tx_hash = ''.join(map(chr, tx_hash))
    else:
        tx_hash = bytes(tx_hash)

    # Create request
    request = endpoint_pb2.TxStatusRequest()
    request.tx_hash = tx_hash

    # Create connection to Iroha
    channel = grpc.insecure_channel('127.0.0.1:50051')
    stub = endpoint_pb2_grpc.CommandServiceStub(channel)

    # Send request
    response = stub.StatusStream(request)

    for status in response:
        print("Status of transaction:")
        print(status)

def send_tx(tx, key_pair):
    tx_blob = proto_tx_helper.signAndAddSignature(tx, key_pair).blob()
    proto_tx = block_pb2.Transaction()

    if sys.version_info[0] == 2:
        tmp = ''.join(map(chr, tx_blob))
    else:
        tmp = bytes(tx_blob)

    proto_tx.ParseFromString(tmp)

    channel = grpc.insecure_channel('127.0.0.1:50051')
    stub = endpoint_pb2_grpc.CommandServiceStub(channel)

    stub.Torii(proto_tx)


def send_query(query, key_pair):
    query_blob = proto_query_helper.signAndAddSignature(query, key_pair).blob()

    proto_query = queries_pb2.Query()

    if sys.version_info[0] == 2:
        tmp = ''.join(map(chr, query_blob))
    else:
        tmp = bytes(query_blob)

    proto_query.ParseFromString(tmp)

    channel = grpc.insecure_channel('127.0.0.1:50051')
    query_stub = endpoint_pb2_grpc.QueryServiceStub(channel)
    query_response = query_stub.Find(proto_query)

    return query_response


########################
class Account:
    def __init__(self, name, keypair):
        self.name = name
        self.keypair = keypair

def add_user(user):
    global tx_counter
    tx = tx_builder.creatorAccountId(creator) \
        .txCounter(tx_counter) \
        .createdTime(get_time()) \
        .createAccount(user.name, 'global', user.keypair.publicKey()) \
        .appendRole(user.name + '@global', 'voter') \
        .build()

    tx_counter += 1

    send_tx(tx, key_pair)
    print_status_streaming(tx)

def add_candidate(candidate, domain, tx_buidler):
    return tx_buidler \
        .createAccount(candidate.name, domain, candidate.keypair.publicKey()) \
        .appendRole(candidate.name + '@' + domain, 'candidate')

def add_voter(voter, domain, tx_buidler):
    return tx_buidler \
        .appendRole(voter + '@global', 'prevote') \
        .transferAsset(creator, voter + '@global', 'vote#' + domain, 'grant 1 vote for ' + domain, '1') \
        .detachRole(voter + '@global', 'prevote')

def add_poll(poll_name, candidates, voters):
    global tx_counter
    tx_buidler = tx_builder.creatorAccountId(creator) \
        .txCounter(tx_counter) \
        .createdTime(get_time()) \
        .createDomain(poll_name, "observer") \
        .createAsset('vote', poll_name, 0) \
        .addAssetQuantity(creator, 'vote#' + poll_name, str(len(voters)))
    for candidate in candidates:
        tx_buidler = add_candidate(candidate, poll_name, tx_buidler)
    for voter in voters:
        tx_buidler = add_voter(voter, poll_name, tx_buidler)
    tx = tx_buidler.build()

    tx_counter += 1

    send_tx(tx, key_pair)
    print_status_streaming(tx)

##########################

def get_account_asset(user, asset):
    global query_counter
    query = query_builder.creatorAccountId(creator) \
        .createdTime(get_time()) \
        .queryCounter(query_counter) \
        .getAccountAssets(user, 'vote#' + poll_name) \
        .build()

    query_response = send_query(query, key_pair)

    query_counter += 1


    return dump_object(query_response)

def dump_object(obj):
    for descriptor in obj.DESCRIPTOR.fields:
        value = getattr(obj, descriptor.name)
        if descriptor.type == descriptor.TYPE_MESSAGE:
            if descriptor.label == descriptor.LABEL_REPEATED:
                map(dump_object, value)
            else:
                return dump_object(value)
        else:
            if descriptor.full_name == 'iroha.protocol.uint256.fourth':
                return value
    return 0

##########################

def vote(voter, candidate, poll_name):
    global tx_counter
    tx = tx_builder.creatorAccountId(voter.name + '@global') \
        .txCounter(tx_counter) \
        .createdTime(get_time()) \
        .transferAsset(voter.name + '@global',
                       candidate + '@' + poll_name,
                       'vote#' + poll_name,
                       'Vote for my candidate. Candidate of the people ' + candidate,
                       '1') \
        .build()

    tx_counter += 1

    send_tx(tx, voter.keypair)
    print_status_streaming(tx)

##########################
# check if voters gives vote to the correct candidate
def check_my_vote(account, asset_id):
    global query_counter
    query = query_builder.creatorAccountId(account.name + '@global') \
        .createdTime(get_time()) \
        .queryCounter(query_counter) \
        .getAccountAssetTransactions(account.name + '@global', asset_id) \
        .build()

    query_response = send_query(query, account.keypair)

    query_counter += 1

    print(query_response)


##########################

tx_counter_user = 1
tx_counter_manager = 1

myname = input('Please enter your account name: ')
alexey = Account(myname, crypto.generateKeypair())

add_user(alexey)

while True:
    print('1 - Create election')
    print('2 - vote')
    print('3 - get vote results')
    action = input('Enter action: ')
    if action == "1":
        poll_name = input("Enter election name: ")
        candidate_str = input("Enter candidates: ")
        candidates = candidate_str.split(" ")
        for i, cand in enumerate(candidates):
            candidates[i] = Account(cand, crypto.generateKeypair())
        voters_str = input("Enter voters: ")
        voters = voters_str.split(" ")
        add_poll(poll_name, candidates, voters)
    elif action == "2":
        vote_name = input('Enter election name: ')
        candidate = input('Enter candidate: ')
        vote(alexey, candidate, vote_name)
    elif action == "3":
        poll_name = input('Enter election name: ')
        candidate = input('Enter candidate: ')
        print(candidate + ' votes: ' + str(get_account_asset(candidate + '@' + poll_name, 'vote#' + poll_name)))
