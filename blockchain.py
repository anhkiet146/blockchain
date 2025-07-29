from ecdsa import SigningKey, VerifyingKey, SECP256k1
import json
import os
import base64
import time
import hashlib

class Transaction:
    def __init__(self, sender_pubkey, username, task_id, progress_text, signature, project_id, phase_id, timestamp=None):
        self.sender = sender_pubkey
        self.username = username
        self.task_id = task_id
        self.progress_text = progress_text
        self.signature = signature
        self.project_id = project_id
        self.phase_id = phase_id
        self.timestamp = timestamp if timestamp is not None else time.ctime()

    def to_dict(self):
        return {
            'sender': self.sender,
            'username': self.username,
            'task_id': self.task_id,
            'progress_text': self.progress_text,
            'signature': self.signature,
            'project_id': self.project_id,
            'phase_id': self.phase_id,
            'timestamp': self.timestamp
        }

    def sign_transaction(self, private_key_hex):
        private_key_bytes = base64.b64decode(private_key_hex)
        private_key = SigningKey.from_string(private_key_bytes, curve=SECP256k1)
        message = f"{self.username}{self.task_id}{self.progress_text}{self.project_id}{self.phase_id}{self.timestamp}".encode()
        self.signature = base64.b64encode(private_key.sign(message)).decode()
        self.sender = private_key.verifying_key.to_string().hex()

    def verify_signature(self):
        try:
            public_key = VerifyingKey.from_string(bytes.fromhex(self.sender), curve=SECP256k1)
            message = f"{self.username}{self.task_id}{self.progress_text}{self.project_id}{self.phase_id}{self.timestamp}".encode()
            signature = base64.b64decode(self.signature)
            return public_key.verify(signature, message)
        except Exception:
            return False

class Wallet:
    def __init__(self):
        self.private_key = SigningKey.generate(curve=SECP256k1)
        self.public_key = self.private_key.verifying_key
        print(f"Generated private key length: {len(self.private_key.to_string())} bytes")

    def get_private_key(self):
        private_key_bytes = self.private_key.to_string()
        if len(private_key_bytes) != 32:
            raise ValueError(f"Invalid private key length: {len(private_key_bytes)} bytes, expected 32")
        return base64.b64encode(private_key_bytes).decode()

    def get_public_key(self):
        public_key_bytes = self.public_key.to_string()
        return base64.b64encode(public_key_bytes).decode()

    def save_to_file(self, filename):
        wallet_data = {
            'private_key': self.get_private_key(),
            'public_key': self.get_public_key()
        }
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'w') as f:
            json.dump(wallet_data, f, indent=4)

    def load_from_file(self, filename):
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                wallet_data = json.load(f)
                private_key_str = wallet_data.get('private_key', '')
                try:
                    private_key_bytes = base64.b64decode(private_key_str)
                    if len(private_key_bytes) != 32:
                        raise ValueError(f"Invalid private key length: {len(private_key_bytes)} bytes, expected 32")
                    self.private_key = SigningKey.from_string(private_key_bytes, curve=SECP256k1)
                    public_key_str = wallet_data.get('public_key', '')
                    public_key_bytes = base64.b64decode(public_key_str)
                    self.public_key = VerifyingKey.from_string(public_key_bytes, curve=SECP256k1)
                    print(f"Successfully loaded wallet from {filename}")
                    return True
                except Exception as e:
                    print(f"Error loading wallet from {filename}: {str(e)}")
                    return False
        return False
    
class Block:
    def __init__(self, index, timestamp, transactions, prev_hash, difficulty=2):
        self.index = index
        self.timestamp = timestamp
        self.transactions = transactions  # Danh sách các Transaction hoặc dict
        self.prev_hash = prev_hash
        self.nonce = 0
        self.difficulty = difficulty
        self.hash = self.calculate_hash()
        self.is_edited = False

    def calculate_hash(self):
        tx_data = [tx.to_dict() if hasattr(tx, 'to_dict') else tx for tx in self.transactions]
        block_string = f"{self.index}{self.timestamp}{json.dumps(tx_data, sort_keys=True)}{self.prev_hash}{self.nonce}"
        return hashlib.sha256(block_string.encode()).hexdigest()

    def mine_block(self, difficulty):
        target = '0' * difficulty
        while self.hash[:difficulty] != target:
            self.nonce += 1
            self.hash = self.calculate_hash()

    def update_transaction(self, task_id, new_progress_text, private_key_hex):
        for tx in self.transactions:
            if tx.task_id == task_id:
                # Tạo giao dịch mới với progress_text cập nhật
                new_tx = Transaction(
                    tx.sender,
                    tx.username,
                    tx.task_id,
                    new_progress_text,
                    "",
                    tx.project_id,
                    tx.phase_id,
                    tx.timestamp
                )
                new_tx.sign_transaction(private_key_hex)
                tx.progress_text = new_progress_text
                tx.signature = new_tx.signature
                self.is_edited = True
                self.hash = self.calculate_hash()  # Tính lại hash
                return True
        return False

class Blockchain:
    def __init__(self, difficulty=2):
        self.chain = []
        self.difficulty = difficulty
        self.pending_transactions = []
        self.create_genesis_block()

    def create_genesis_block(self):
        genesis_block = Block(0, time.ctime(), [], "0", self.difficulty)
        genesis_block.mine_block(self.difficulty)
        self.chain.append(genesis_block)

    def get_latest_block(self):
        return self.chain[-1]

    def add_transaction(self, transaction):
        if transaction.verify_signature():
            self.pending_transactions.append(transaction)
            return True
        return False

    def mine_pending_transactions(self):
        if not self.pending_transactions:
            return False
        block = Block(len(self.chain), time.ctime(), self.pending_transactions, self.get_latest_block().hash, self.difficulty)
        block.mine_block(self.difficulty)
        self.chain.append(block)
        self.pending_transactions = []
        return True

    def update_transaction_in_chain(self, project_id, task_id, new_progress_text, private_key_hex):
        for block in reversed(self.chain):
            if any(tx.task_id == task_id for tx in block.transactions):
                if block.update_transaction(task_id, new_progress_text, private_key_hex):
                    block.mine_block(self.difficulty)  # Tính lại hash sau khi chỉnh sửa
                    return True
        return False

    def is_chain_valid(self):
        for i in range(1, len(self.chain)):
            current = self.chain[i]
            previous = self.chain[i-1]
            if current.hash != current.calculate_hash():
                return False
            if current.prev_hash != previous.hash:
                return False
            for tx in current.transactions:
                if not tx.verify_signature():
                    return False
        return True

    def save_to_file(self, filename):
        chain_data = []
        for block in self.chain:
            block_dict = block.__dict__.copy()
            block_dict['transactions'] = [tx.to_dict() for tx in block.transactions if hasattr(tx, 'to_dict')]
            chain_data.append(block_dict)
        
        data = {
            'chain': chain_data,
            'chain_hash': hashlib.sha256(str(chain_data).encode()).hexdigest()
        }
        with open(filename, 'w') as file:
            json.dump(data, file, indent=2)

    def load_from_file(self, filename):
        try:
            with open(filename, 'r') as file:
                data = json.load(file)
                self.chain = []
                for block_data in data['chain']:
                    transactions = []
                    for tx_data in block_data['transactions']:
                        transaction = Transaction(
                            tx_data['sender'],
                            tx_data['username'],
                            tx_data['task_id'],
                            tx_data['progress_text'],
                            tx_data['signature'],
                            tx_data['project_id'],
                            tx_data['phase_id'],
                            tx_data['timestamp']
                        )
                        transactions.append(transaction)
                    block = Block(
                        block_data['index'],
                        block_data['timestamp'],
                        transactions,
                        block_data['prev_hash'],
                        block_data['difficulty']
                    )
                    block.nonce = block_data['nonce']
                    block.hash = block_data['hash']
                    block.is_edited = block_data['is_edited']
                    self.chain.append(block)
                return True
        except Exception as e:
            print(f"Error loading blockchain from {filename}: {str(e)}")
            return False